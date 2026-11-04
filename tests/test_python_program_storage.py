"""Bound upload history without hardware, MQTT or files outside a temp folder."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vehicle_testing.runtime import python_program as runtime


class ProgramStorageTests(unittest.TestCase):
    def seed_history(self, folder, count=3):
        pairs = []
        for index in range(count):
            program_id = f'{index + 1:032x}'
            source = folder / f'{program_id}.fe.txt'
            target = folder / f'{program_id}.py'
            source.write_text(f'robot.sendCmd("led_strip:OLD {index}")', encoding='utf-8')
            target.write_text(f'# old program {index}\n', encoding='utf-8')
            # Future timestamps also prove the incoming upload is always kept.
            stamp = 2_000_000_000_000_000_000 + index * 1_000_000_000
            for path in (source, target):
                os.utime(path, ns=(stamp, stamp))
            pairs.append((source, target))
        return pairs

    def snapshot(self, folder):
        return {path.name: path.read_bytes() for path in folder.iterdir() if path.is_file()}

    def test_repeated_uploads_keep_only_the_three_latest_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            programs = []
            for index in range(8):
                source = f'report_block("upload-{index}") robot.sendCmd("led_strip:TEST {index}")'
                program = runtime.prepare_program(source, folder)
                programs.append(program)
                self.assertEqual(program.source_path.read_text(encoding='utf-8'), source)
                self.assertIn(f"robot.report_block('upload-{index}')",
                              program.path.read_text(encoding='utf-8'))
                # Deterministic ordering without sleeps or relying on clock precision.
                for path in (program.source_path, program.path):
                    stamp = (index + 1) * 1_000_000_000
                    os.utime(path, ns=(stamp, stamp))
                expected = {path.name for item in programs[-3:]
                            for path in (item.source_path, item.path)}
                self.assertEqual({path.name for path in folder.iterdir()}, expected)

    def test_first_successful_upload_prunes_legacy_history_and_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pairs = self.seed_history(folder, count=7)
            notes = folder / 'notes.py'
            notes.write_text('# keep user file\n', encoding='utf-8')
            named_source = folder / 'manual.fe.txt'
            named_source.write_text('keep this too', encoding='utf-8')
            subdirectory = folder / f'{100:032x}.py'
            subdirectory.mkdir()
            program = runtime.prepare_program('robot.sendCmd("stop")', folder)
            expected = {path.name for pair in pairs[-2:] for path in pair}
            expected.update((program.source_path.name, program.path.name,
                             notes.name, named_source.name, subdirectory.name))
            self.assertEqual({path.name for path in folder.iterdir()}, expected)
            self.assertEqual(notes.read_text(encoding='utf-8'), '# keep user file\n')

    def test_invalid_upload_preserves_all_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.seed_history(folder, count=5)
            before = self.snapshot(folder)
            for source in ('import os', 'robot.sendCmd("hand_up:91")',
                           'robot.sendCmd("led_strip:🙂")'):
                with self.subTest(source=source), self.assertRaises(ValueError):
                    runtime.prepare_program(source, folder)
                self.assertEqual(self.snapshot(folder), before)

    def test_failed_second_write_keeps_old_pairs_and_leaves_no_partial_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.seed_history(folder)
            before = self.snapshot(folder)
            write_text = Path.write_text

            def fail_python_write(path, *args, **kwargs):
                if path.suffix == '.py':
                    raise OSError('disk full')
                return write_text(path, *args, **kwargs)

            with patch.object(Path, 'write_text', fail_python_write):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    runtime.prepare_program('robot.sendCmd("stop")', folder)
            self.assertEqual(self.snapshot(folder), before)
            self.assertEqual(len(list(folder.iterdir())), 6)

    def test_failed_second_commit_rolls_back_new_pair_before_pruning(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.seed_history(folder)
            before = self.snapshot(folder)
            replace = Path.replace

            def fail_python_commit(path, target):
                if path.suffix == '.py':
                    raise OSError('cannot commit Python file')
                return replace(path, target)

            with patch.object(Path, 'replace', fail_python_commit):
                with self.assertRaisesRegex(OSError, 'cannot commit'):
                    runtime.prepare_program('robot.sendCmd("stop")', folder)
            self.assertEqual(self.snapshot(folder), before)
            self.assertEqual(len(list(folder.iterdir())), 6)

    def test_cleanup_error_is_logged_without_rejecting_the_saved_program(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            pairs = self.seed_history(folder, count=5)
            blocked_target = pairs[2][1]
            unlink = Path.unlink

            def deny_one_old_file(path, *args, **kwargs):
                if path == blocked_target:
                    raise PermissionError('old file is read-only')
                return unlink(path, *args, **kwargs)

            with patch.object(Path, 'unlink', deny_one_old_file):
                with self.assertLogs(runtime.logger, level='WARNING') as logs:
                    program = runtime.prepare_program('robot.sendCmd("stop")', folder)
            self.assertTrue(program.source_path.is_file())
            self.assertTrue(program.path.is_file())
            self.assertIn(blocked_target.stem, '\n'.join(logs.output))
            self.assertTrue(blocked_target.is_file())
            for pair in pairs[:2]:
                self.assertTrue(all(not path.exists() for path in pair))


if __name__ == '__main__':
    unittest.main()
