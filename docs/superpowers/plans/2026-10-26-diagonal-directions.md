# Remaining diagonal directions

User request: extend the tested 3*pi/4 forward-left movement with pi/4,
-3*pi/4 and -pi/4, using the same chassis coordinates and timed CLI.

## Design

| Angle | Controller method | CLI | Active wheels |
| --- | --- | --- | --- |
| pi/4 | move_forward_right | tren_phai | FL/RR forward |
| -3*pi/4 | move_backward_left | duoi_trai | FL/RR backward |
| -pi/4 | move_backward_right | duoi_phai | FR/RL backward |

Reuse the existing timed driver with None for disabled wheels. Share the
four-wheel and duration/PWM validation between the four diagonal methods;
preserve move_forward_left's signature and outputs. CLI commands take seconds
and optional PWM, queue until chay and use DEFAULT_SPEED when PWM is omitted.
No gains, arbitrary-angle mixer, config changes or firmware changes.

Reference: https://seamonsters-2605.github.io/archive/mecanum/ .
FR/RL = sin(angle-pi/4), FL/RR = sin(angle+pi/4).
Negative angles match the equivalent 5*pi/4 and 7*pi/4 table columns.

## Implementation and checks

- [x] Add failing tests for all three missing controller methods and commands.
- [x] Implement shared diagonal validation and the three methods/CLI commands.
- [x] Check signed outputs, disabled wheels under inversion, direction-before-PWM,
  transitions between pairs, invalid input, partial startup and interruption.
- [x] Check mixed queues, cancellation, no replay, default PWM and both CLI entry points.
- [x] Update README with all four angles and commands.
- [x] Run the complete suite, diff checks and independent read-only review.

## Verification boundary

The user reports forward-left physical testing was successful. New directions
are verified in software only until tested on the actual vehicle.

## Results

RED: added controller/parser tests failed on the three missing methods and
commands. GREEN: all 16 diagonal tests passed, including the existing forward-left
regressions. The complete suite passed: 74 tests in 21.609 s.

Both direct and module CLI entry points passed dry-run/verbose integration with
all four diagonals. Checks verified signed direction channels, exactly the active
pair's PWM, execution once in queue order and no replay on a second chay.
config.py matches HEAD exactly and git diff --check passed.

Independent read-only review found no actionable issues. Physical angle, wheel
installation and driver braking/coasting remain outside software verification.
