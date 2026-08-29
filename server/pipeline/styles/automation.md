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
it called `get_snapshot("evt_005")` and `get_snapshot("evt_006")`, because
"the list re-ordered" is a claim about POSITION and no diff summary can settle
one. For the refusal it called `get_network("evt_007")`: the page said
"This booking has already started", which is the message, and the 409 is the
behaviour -- and a status code that appears in the session index but in no
retrieval is not something you may claim.

It called `see("evt_006")` exactly once, and only because the two sort
snapshots came back with the same twelve names in a different order and the
accessibility tree gave no clue which order was "latest". The screenshot showed
the dates descending. **The picture told it where to look; the claim below
still quotes a string a text retrieval returned.** Most sessions need no
screenshot at all.

```gherkin
Feature: Meeting room booking

  Booking a room confirms it, removes it from availability, and cannot be
  undone once the booking has started.

  Scenario: Booking a room reduces the number free
    Given the tester searches for an available room
    When the tester books the Ada Lovelace Room for 2 hours
    Then the room is confirmed for 14:00 to 16:00
    And the number of free rooms drops from 3 to 2

  Scenario: A confirmed booking appears in the tester's own list
    When the tester opens their own bookings

  Scenario Outline: Sorting the bookings list reorders it
    When the tester sorts the bookings by <order>
    Then the first booking shown is <first>

    Examples:
      | order   | first                |
      | Soonest | Ada Lovelace Room    |
      | Latest  | Grace Hopper Room    |

  Scenario: A booking that has already started cannot be cancelled
    When the tester cancels the Ada Lovelace Room booking
    Then the booking is refused with a 409 Conflict
    And the bookings list no longer offers to cancel it
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
      "line": "the tester searches for an available room",
      "id": "step_001",
      "role": "setup",
      "events": [
        "evt_001"
      ]
    },
    {
      "kind": "step",
      "line": "the tester books the Ada Lovelace Room for 2 hours",
      "id": "step_002",
      "role": "test_step",
      "events": [
        "evt_002",
        "evt_003"
      ]
    },
    {
      "kind": "verdict",
      "line": "the room is confirmed for 14:00 to 16:00",
      "evidence": {
        "eventId": "evt_003",
        "literal": "Booked: Ada Lovelace Room, 14:00-16:00"
      }
    },
    {
      "kind": "verdict",
      "line": "the number of free rooms drops from 3 to 2",
      "evidence": {
        "eventId": "evt_003",
        "literal": "2 rooms free"
      }
    },
    {
      "kind": "step",
      "line": "the tester opens their own bookings",
      "id": "step_003",
      "role": "test_step",
      "events": [
        "evt_004"
      ],
      "whyNot": "The bookings page replaced most of the screen and nothing on it names the room that was just booked, so there is no way to tell this list apart from any other list of bookings."
    },
    {
      "kind": "step",
      "line": "the tester sorts the bookings by <order>",
      "id": "step_004",
      "role": "test_step",
      "events": [
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
      "line": "the tester cancels the Ada Lovelace Room booking",
      "id": "step_005",
      "role": "test_step",
      "events": [
        "evt_007"
      ]
    },
    {
      "kind": "verdict",
      "line": "the booking is refused with a 409 Conflict",
      "evidence": {
        "eventId": "evt_007",
        "literal": "409",
        "kind": "network"
      }
    },
    {
      "kind": "verdict",
      "line": "the bookings list no longer offers to cancel it",
      "evidence": {
        "eventId": "evt_007",
        "literal": "Cancel booking",
        "predicate": {
          "form": "absent"
        }
      }
    }
  ],
  "omitted": []
}
```

Seven things in that answer are worth copying.

**The verdict is the count, not the confirmation banner.** Both were on the
page. Break the availability feature and "Booked: ..." still appears, so a test
resting only on the banner passes on a broken build. The count is what the
feature computes.

**The sort claim says `first_of`, not "contains".** *"Grace Hopper Room"* is in
the list whichever way it is sorted. Only its POSITION distinguishes a working
sort from a broken one, and `first_of` is what makes the checker ask about
position. Writing that verdict without the predicate would be a sentence saying
FIRST resting on a check that only says PRESENT.

**Two sorts became one `Scenario Outline`, not two scenarios.** The flow is the
same and only the values differ. Written out twice it reads as a transcript;
written as a table it reads as a test somebody designed. Use `<angle brackets>`
in the step text and give the table two rows or more -- one row is not a table.

**The 409 is cited from `get_network`, not from the index.** The session index
prints status codes and the index is a SUMMARY, so a claim resting on it points
at nothing. The alert on the page said "This booking has already started",
which is a different fact from "the request was refused with 409". A sentence
and its literal must be about the same thing.

**The cancel button being gone is `absent`.** A negative claim cannot be proved
by quoting a string, because the string is not there. It cites the retrieval it
is ABOUT, and the checker confirms nothing in that whole-page retrieval says it.

**step_003 refuses, and says why in a sentence its tester can act on.** That is
worth more than a claim about a heading being present. Never write an expected
result that amounts to "the page appeared".

**Four scenarios, decided while writing.** They check different things.
