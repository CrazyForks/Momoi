Infer current state changes from the conversation records above for pending_turns. If evidence conflicts, use the latest Turn.

Maintain current state. State is short-term, TTL-backed working memory for temporary facts that would make your behavior wrong, right now, if forgotten — because they override a long-term default, or because they're a new temporary fact too immediate/short-lived for the 7-day recent memory or on-demand recall to reliably surface in time.

Test before adding: "If I forget this, will I say or do something wrong within its real-world time scope?" If no — skip it, no matter how notable or memorable. Weak reasons ("might be useful," "low risk," "could support continuity") never justify adding a slot.

Check memory before state: if the fact is durable — a rule, preference, relationship, procedure, or cross-event state still worth knowing after its moment passes — record it with `memory_operation` instead of adding a slot. State is only a short-term state or behavior that can change or be forgotten within its real-world scope.

Examples:
* "Took a taxi to work today" — overrides long-term default "commutes by bike." Ends at midnight.
* "Napping until 2pm" — new temporary fact, not a default override. Delete early if person says they can't sleep.
* "Off work today" — overrides default work schedule. Ends at midnight.
* Anti-example: person jokingly calls you a nickname, teases you. Forgetting it breaks nothing — belongs to mood tracking, not state. Do not add.

Each value is one concise state; keep evidence separate. Submit status=observed only for what the source directly states; deductions require status=inferred and a nonempty uncertainty. Supply source_turn using its T-N transcript label and source as an exact quote from one message. Runtime validates the quote and derives its speaker and time. Never invent evidence or timestamps. Assistant suggestions are not owner promises. A recorded inventory issue does not establish whether a meal is still cooking or already eaten. Lack of a follow-up message does not keep a short activity ongoing.

Existing states expose source time, speaker and uncertainty. Read these before relying on a state. Old unverified states are marked inferred; do not upgrade them to observed without direct evidence. Preserve original evidence time when rephrasing. Expiry controls retention, not certainty. Maintenance-only IDs identify slots for deletion; no owner message is sent.

Every pass: review and normalize all slots. Delete anything ended, conflicting, duplicated, or no longer meeting the test above. If a slot mixes fact with history, replace it with one clean version — never leave malformed content. Replace changed facts by deleting the old slot and adding one successor.

TTL = remaining real-world scope of the fact, not importance. Use explicit duration/date when given; unscoped "today" facts end at local midnight. Never fall back to habitual round numbers like 24/12/8 hours — derive the TTL from the fact's actual lifecycle: a nap ends in minutes, a work arrangement ends at its stated time, being out in the rain ends at dry clothes. When torn between two windows, pick the shorter defensible one. If no clear TTL or ongoing applicability exists, don't add it. Delete early when new evidence ends it.

Default to exclusion when ambiguous. Return empty `add`/`delete` when nothing materially changes.
Typical flow: … → memory_operation? → current_state_finish
