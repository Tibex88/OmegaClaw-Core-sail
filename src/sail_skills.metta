; SAIL skills for OmegaSen.
;
; Each skill wraps a call into the game_ws channel (channels/game_ws.py) and
; returns a short status string that the MeTTa loop can feed back to the LLM
; through LAST_SKILL_USE_RESULTS. Skills are registered with add-skill so
; they appear in the prompt's SKILLS section.

; ------- Perception -----------------------------------------------------------

(= (perceive)
   (py-call (game_ws.perceive)))

; ------- Movement primitives --------------------------------------------------

(= (rotate-left)
   (py-call (game_ws.send_action "RotateLeft" ({}))))
(= (rotate-left $degrees)
   (py-call (game_ws.send_action "RotateLeft" ({"Degrees": $degrees}))))

(= (rotate-right)
   (py-call (game_ws.send_action "RotateRight" ({}))))
(= (rotate-right $degrees)
   (py-call (game_ws.send_action "RotateRight" ({"Degrees": $degrees}))))

(= (move-ahead)
   (py-call (game_ws.send_action "MoveAhead" ({}))))
(= (move-ahead $distance)
   (py-call (game_ws.send_action "MoveAhead" ({"Distance": $distance}))))

(= (move-back)
   (py-call (game_ws.send_action "MoveBack" ({}))))
(= (move-back $distance)
   (py-call (game_ws.send_action "MoveBack" ({"Distance": $distance}))))

(= (move-left)
   (py-call (game_ws.send_action "MoveLeft" ({}))))
(= (move-left $distance)
   (py-call (game_ws.send_action "MoveLeft" ({"Distance": $distance}))))

(= (move-right)
   (py-call (game_ws.send_action "MoveRight" ({}))))
(= (move-right $distance)
   (py-call (game_ws.send_action "MoveRight" ({"Distance": $distance}))))

; ------- Waypoint navigation --------------------------------------------------

(= (move-to $target)
   (py-call (game_ws.send_action "MoveTo" ({"Target": $target}))))

; ------- Interaction ----------------------------------------------------------

(= (interact)
   (py-call (game_ws.send_action "Interact" ({}))))
(= (interact $target)
   (py-call (game_ws.send_action "Interact" ({"Target": $target}))))

; ------- Interruption --------------------------------------------------------

(= (cancel)
   (py-call (game_ws.send_action "Cancel" ({}))))

; ------- Lifecycle wait -------------------------------------------------------

(= (wait-terminal)
   (py-call (game_ws.wait_for_terminal 15.0)))
(= (wait-terminal $seconds)
   (py-call (game_ws.wait_for_terminal $seconds)))

; ------- Skill registration --------------------------------------------------

(= (initSailSkills)
   (progn
     (log INFO "sail" "Registering SAIL skills")
     (add-skill perceive       "Read the current SAIL snapshot (position, visible entities with distance/angle/kinds, actions currently available to the Player)" ())
     (add-skill rotate-left    "Rotate the Player 15 degrees to the left" ())
     (add-skill rotate-left    "Rotate the Player by a specific number of degrees to the left (1..90)" (degrees))
     (add-skill rotate-right   "Rotate the Player 15 degrees to the right" ())
     (add-skill rotate-right   "Rotate the Player by a specific number of degrees to the right (1..90)" (degrees))
     (add-skill move-ahead     "Step the Player forward by the default 0.5 meters" ())
     (add-skill move-ahead     "Step the Player forward by a specific distance in meters (0.1..2.0)" (distance))
     (add-skill move-back      "Step the Player backward by the default 0.5 meters" ())
     (add-skill move-back      "Step the Player backward by a specific distance in meters (0.1..2.0)" (distance))
     (add-skill move-left      "Sidestep the Player left by the default 0.5 meters" ())
     (add-skill move-left      "Sidestep the Player left by a specific distance in meters (0.1..2.0)" (distance))
     (add-skill move-right     "Sidestep the Player right by the default 0.5 meters" ())
     (add-skill move-right     "Sidestep the Player right by a specific distance in meters (0.1..2.0)" (distance))
     (add-skill move-to        "NavMesh path the Player to a destination (name must appear in the current AvailableActions.Player.MoveTo list)" (target))
     (add-skill interact       "Interact with whatever the Player is currently pointed at" ())
     (add-skill interact       "Interact with a specific visible entity (Name from perceive())" (target))
     (add-skill cancel         "Interrupt the currently in-flight Player action" ())
     (add-skill wait-terminal  "Block up to 15 seconds waiting for the current action to reach completed/failed/cancelled/rejected" ())
     (add-skill wait-terminal  "Block up to N seconds waiting for the current action to reach terminal status" (seconds))
     (add-prompt-extension sail
       "SAIL RULES: You are OmegaSen and you control the Player in a 3D SophiaVerse scene. Each iteration begins with a SNAPSHOT summary. Only pick actions that appear in the snapshot's actions block. Only one Player action can run at a time (Cancel interrupts). Prefer small primitives; use move-to when a destination is advertised.")))

!(initSailSkills)
