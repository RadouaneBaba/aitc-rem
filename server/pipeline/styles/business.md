Here is one good answer, on a different application, end to end.

The session index said:

    evt_001  click  button "Find a room"              | +12 -0 ~0 | "3 rooms free"
    evt_002  select combobox "Duration" -> "2 hours"  | +0 -0 ~1  | "14:00-16:00"
    evt_003  click  button "Book Ada Lovelace Room"   | POST /api/bookings 201
             +4 -1 ~1 | "Booked: Ada Lovelace Room, 14:00-16:00" | "2 rooms free"
    evt_004  click  link "My bookings"                | url -> /bookings | +31 -22 ~0
    evt_005  select combobox "Sort" -> "Soonest"      | +18 -18 ~0
    evt_006  select combobox "Sort" -> "Latest"       | +18 -18 ~0
    evt_007  click  button "Cancel booking"           | POST /api/bookings/88/cancel 409
             +2 -0 ~1 | "This booking has already started"

The tester expected: "booking a room should take it out of the free count", and
"cancelling after the start time should be refused".

What the author did, and it is the shape of the work rather than a number of
calls: it called `get_diff("evt_003")`, saw the count change, and called
`find_text("2 rooms free")` to be sure of the wording. It spent nothing on
evt_001 or evt_002, because nothing about them was in doubt. For the two sorts
it called `get_snapshot("evt_006")`, because "the list re-ordered" is a claim
about POSITION and no diff summary can settle one. For the refusal it called
`get_network("evt_007")`: the page said "This booking has already started",
which is the message, and the 409 is the behaviour -- and a status code that
appears in the session index but in no retrieval is not something you may claim.

It called `see("evt_006")` exactly once, and only because the sort snapshots
came back with the same twelve names in a different order and the accessibility
tree gave no clue which order was "latest". The screenshot showed the dates
descending. **The picture told it where to look; the claim below still quotes a
string a text retrieval returned.** Most sessions need no screenshot at all.

```gherkin
Feature: Meeting room booking

  Staff book rooms from a shared pool, and a room that is booked stops being
  offered to anyone else.

  Scenario: Booking a room takes it out of the pool
    Given a room is free for the afternoon
    When the tester books it for two hours
    Then the room is confirmed and the number of free rooms drops from 3 to 2

  Scenario Outline: Staff can order their bookings by when they start
    When the tester sorts the bookings by <order>
    Then the first booking shown is <first>

    Examples:
      | order   | first             |
      | Soonest | Ada Lovelace Room |
      | Latest  | Grace Hopper Room |

  Scenario: A booking that has already started can no longer be cancelled
    Given the tester has a booking that started earlier today
    When the tester tries to cancel it
    Then the cancellation is refused and the option is withdrawn
```

```json
{
  "title": "Meeting room booking",
  "tags": [
    "booking"
  ],
  "annotations": [
    {
      "kind": "step",
      "line": "a room is free for the afternoon",
      "id": "step_001",
      "role": "setup",
      "events": [
        "evt_001"
      ]
    },
    {
      "kind": "step",
      "line": "the tester books it for two hours",
      "id": "step_002",
      "role": "test_step",
      "events": [
        "evt_002",
        "evt_003"
      ]
    },
    {
      "kind": "verdict",
      "line": "the room is confirmed and the number of free rooms drops from 3 to 2",
      "evidence": {
        "eventId": "evt_003",
        "literal": "2 rooms free"
      }
    },
    {
      "kind": "step",
      "line": "the tester sorts the bookings by <order>",
      "id": "step_003",
      "role": "test_step",
      "events": [
        "evt_004",
        "evt_005",
        "evt_006"
      ]
    },
    {
      "kind": "verdict",
      "line": "the first booking shown is <first>",
      "evidence": {
        "eventId": "evt_006",
        "literal": "Grace Hopper Room",
        "predicate": {
          "form": "first_of",
          "container": {
            "role": "list",
            "name": "Bookings"
          }
        }
      }
    },
    {
      "kind": "step",
      "line": "the tester has a booking that started earlier today",
      "id": "step_004",
      "role": "setup",
      "events": []
    },
    {
      "kind": "step",
      "line": "the tester tries to cancel it",
      "id": "step_005",
      "role": "test_step",
      "events": [
        "evt_007"
      ]
    },
    {
      "kind": "verdict",
      "line": "the cancellation is refused and the option is withdrawn",
      "evidence": {
        "eventId": "evt_007",
        "literal": "409",
        "kind": "network"
      }
    }
  ],
  "omitted": []
}
```

Seven things in that answer are worth copying.

**One verdict per scenario, at the end.** This style is read by people deciding
whether the behaviour is right, not by someone writing step definitions. Two
observations that belong to one outcome are one sentence: *"the room is
confirmed and the number of free rooms drops from 3 to 2"*, not two lines.

**The verdict is still the count, not the confirmation banner.** Plain language
is not permission to assert less. Break the availability feature and
"Booked: ..." still appears, so a test resting on the banner passes on a broken
build. The count is what the feature computes, and the sentence names it.

**The sort claim says `first_of`, not "contains".** *"Grace Hopper Room"* is in
the list whichever way it is sorted. Only its POSITION distinguishes a working
sort from a broken one.

**Two sorts became one `Scenario Outline`.** The flow is the same and only the
values differ. Written out twice it reads as a transcript; as a table it reads
as a test somebody designed. Two rows minimum -- one row is not a table.

**The 409 is cited from `get_network`, not from the index.** The session index
prints status codes and the index is a SUMMARY, so a claim resting on it points
at nothing. The page said "This booking has already started", which is a
different fact from "the request was refused". A sentence and its literal must
be about the same thing.

**step_004 has no events.** *"the tester has a booking that started earlier
today"* is state, not an action, and this style says such things out loud rather
than making the reader infer them. Do not invent a click to hang it on.

**Mechanics are left out on purpose.** No dropdown names, no button labels, no
element wording -- *"the tester tries to cancel it"*, not *"clicks the Cancel
booking button in the row for booking 88"*. A test written against the mechanism
breaks when the button moves.
