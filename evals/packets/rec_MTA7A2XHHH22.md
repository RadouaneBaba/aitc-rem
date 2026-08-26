# `rec_MTA7A2XHHH22` — judgement packet

Run: `runs/rec_MTA7A2XHHH22/run_002`  ·  set: **held-out**  ·  15 recorded events  ·  2 test case(s)

---

## 1 · What the tester said they were doing

**Objective:** check if filters are working correctly

**What the tester marked:** nothing. No intent notes, no marked elements, no declared breaks.

**Narration:** none.

---

## 2 · What came out

```gherkin
# aitc-rem - rec_MTA7A2XHHH22 - 2026-08-26 - evidence: tc_rec_MTA7A2XHHH22_01.trace.md

@filtering @sorting
Feature: Product filtering

  Verify that product sorting and filtering options correctly update the
  displayed product list

  Background:
    Given the tester is on the "PC Gamer" product category page

  Scenario: Sorting products by price
    When the tester sorts products by "Prix haut à bas"
    And the tester changes the sort order to "Prix bas à haut"

# aitc-rem - rec_MTA7A2XHHH22 - 2026-08-26 - evidence: tc_rec_MTA7A2XHHH22_02.trace.md

@filtering @sorting @needs-review
Feature: Product filtering

  Verify that product sorting and filtering options correctly update the
  displayed product list

  Background:
    Given the tester is on the "PC Gamer" product category page

  Scenario: Filtering products by stock status and processor model
    When the tester filters by "In stock" products
    Then the product list is filtered to show only available items

    When the tester clears the stock filter
    And the tester applies multiple processor model filters
    Then the product list updates to show items matching the selected processors

    When the tester clears all processor filters
    Then the product list updates to show all products
```

---

## 3 · Every step, beside the events it claims and the evidence it reached

### Scenario: Sorting products by price  *(kind: test_case)*

tags: @filtering @sorting

**Given the tester is on the "PC Gamer" product category page**  `step_001` role=setup
    `evt_001`  click      generic ""

**When the tester sorts products by "Prix haut à bas"**  `step_002` role=test_step
    `evt_002`  click      combobox "Sort filter"
    `evt_003`  select     combobox "Sort filter"  = "Prix haut à bas"  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1

**And the tester changes the sort order to "Prix bas à haut"**  `step_003` role=test_step
    `evt_004`  click      combobox "Sort filter"
    `evt_005`  select     combobox "Sort filter"  = "Prix bas à haut"  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1

### Scenario: Filtering products by stock status and processor model  *(kind: test_case)*

tags: @filtering @sorting

**When the tester filters by "In stock" products**  `step_004` role=test_step
    `evt_006`  click      combobox "Sort filter"
    `evt_007`  click      combobox "Sort filter"
    `evt_008`  click      generic ""
    `evt_009`  click      checkbox ""  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1  (no_accessible_name, rapid_sequence)
    **Then** the product list is filtered to show only available items
        evidence: "https://setupgame.ma/categorie-produit/pc-gamer-maroc/query/meta/_stock_status:instock/sort/orderby:price;order:ASC/"  (url via `tc_0022` at `evt_009`)  provenance=objective

**When the tester clears the stock filter**  `step_005` role=test_step
    `evt_010`  click      generic ""  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1

**And the tester applies multiple processor model filters**  `step_006` role=test_step
    `evt_011`  click      generic ""
    `evt_012`  click      checkbox ""  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1  (no_accessible_name, rapid_sequence)
    `evt_013`  click      generic ""
    `evt_014`  click      checkbox ""  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1  (no_accessible_name, rapid_sequence)
    **Then** the product list updates to show items matching the selected processors
        evidence: "Results updated."  (semantic_node via `tc_0025` at `evt_014`)  provenance=objective

**When the tester clears all processor filters**  `step_007` role=test_step
    `evt_015`  click      generic ""  -> 200 POST https://setupgame.ma/categorie-produit/pc-gamer-maroc/?jsf_ajax=1  -> None POST https://www.youtube.com/api/stats/qoe?fmt=398&afmt=251&cpn=74cq5oJTTl…
    **Then** the product list updates to show all products
        evidence: "9 produits affichés"  (semantic_node via `tc_0032` at `evt_015`)  provenance=objective

---

## 4 · Proposed and refused

- **unsupported** on `step_003`: the product list updates to show lower-priced items first
  - refused because: 'Prix bas à haut' is what the tester selected or entered at this event, not what the application did with it. Quote what CHANGED instead
- **unsupported** on `step_003`: the sort filter displays 'Prix bas à haut' and the product list updates to show items sorted by price in ascending order
  - refused because: 'Prix bas à haut' is what the tester selected or entered at this event, not what the application did with it. Quote what CHANGED instead
- **revise** on `step_007`: the product list updates to show all products
  - refused because: The tester clicked a button that cleared the filters, and the product list updated to show 9 products instead of the filtered list.

---

## 5 · What the gate said

**Rejections:** none

**Warnings:** 
- gherkin_style — no Then step: this describes what the tester did but never what should be true afterwards, which is a transcript rather than a test case
- gherkin_style — scenario 'Sorting products by price' ends on an action rather than an expected result, so it has no verdict: the last line is And 'the test…

**Critic:** did not run — `CassetteMiss: no cassette for 21209eec9610... and the run is read_only. Re-run with cassetteMode=read_write to record i…`

| metric | value |
|---|---|
| assertions accepted | `3` |
| grounding rate | `1.0` |
| validator pass (first) | `0.8333333333333334` |
| validator pass (final) | `0.8333333333333334` |
| critic findings raised / resolved | `0 / 0` |
| repair attempts | `0` |
| tool calls total | `33` |
| tool calls per step | `{'step_003': 5, 'step_004': 7, 'step_006': 10, 'step_007': 10}` |

**Splitter:** `{"decisions": [], "scenariosAdded": 0}`

