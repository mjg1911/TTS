# Non-blocking runtime errors

Approved behavior: runtime errors stay visible in a dismissible window while
Piper continues processing commands. Repeated errors update one window.

Implementation in the current branch:

- Add real Tk regression coverage for processing callbacks with an error open,
  updating the existing window, dismissal/reopening, and main-thread access.
- Replace `TkUi.show_status` with a modeless `Toplevel`, wrapping message label,
  and Dismiss button. Do not grab input, wait for dismissal, or force focus.
- Keep fatal startup messages modal through `show_startup_status`, since the app
  exits immediately after those failures. Route pitch/speed validation errors
  through the non-blocking runtime display.
- Run the regression tests and the Windows tray suite; review the final diff.
