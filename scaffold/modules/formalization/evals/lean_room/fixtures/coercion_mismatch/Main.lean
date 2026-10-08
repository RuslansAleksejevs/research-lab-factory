inductive P : Prop where
  | intro : P

inductive Q : Prop where
  | intro : Q

instance : Coe P Q where
  coe _ := Q.intro

-- This declaration can be coerced to Q, but its actual type is P.
theorem lean_room_expected : P := P.intro
