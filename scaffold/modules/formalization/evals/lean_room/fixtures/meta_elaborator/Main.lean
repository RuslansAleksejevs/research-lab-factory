import Lean

open Lean Elab Command

-- A certificate case must never be allowed to replace diagnostic command
-- elaboration.  This adversarial fixture is rejected statically before build.
@[command_elab Lean.Parser.Command.print] meta def forgedPrint : CommandElab :=
  fun _ => pure ()

theorem lean_room_expected : 1 + 1 = 2 := by
  rfl
