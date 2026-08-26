# `rec_MT7MXBS9B2VB` — judgement packet

Run: `runs/rec_MT7MXBS9B2VB/run_001`  ·  set: **held-out**  ·  34 recorded events  ·  2 test case(s)

---

## 1 · What the tester said they were doing

**Objective:** check if hamper sizes change correctly

**What the tester marked:** nothing. No intent notes, no marked elements, no declared breaks.

**Narration:** none.

---

## 2 · What came out

```gherkin
# aitc-rem - rec_MT7MXBS9B2VB - 2026-08-26 - evidence: tc_rec_MT7MXBS9B2VB_01.trace.md

@hampers
Feature: Hamper size adjustment

  The hamper size automatically upgrades when the number of items exceeds the
  current capacity

  Background:
    Given the tester navigates to the "Create Your Own Hamper" page

  Scenario: A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached
    When the tester adds items to the "Small Wicker Basket" until it reaches capacity
    And the tester increases the quantity of items until the hamper upgrades to a "Medium Wicker Basket"
    Then the hamper is shown as a "Medium Wicker Basket"

    # 1 abandoned action(s) omitted - tester clicked cancel after reaching the maximum hamper size. See the review UI.

# aitc-rem - rec_MT7MXBS9B2VB - 2026-08-26 - evidence: tc_rec_MT7MXBS9B2VB_02.trace.md

@hampers
Feature: Hamper size adjustment

  The hamper size automatically upgrades when the number of items exceeds the
  current capacity

  Background:
    Given the tester navigates to the "Create Your Own Hamper" page

  Scenario: A hamper automatically upgrades to a Large Wicker Basket when capacity is reached
    When the tester increases the item quantity until the "Large Wicker Basket" upgrade is triggered
    Then the hamper is shown as a "Large Wicker Basket"
```

---

## 3 · Every step, beside the events it claims and the evidence it reached

### Scenario: A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached  *(kind: test_case)*

tags: @hampers

**Given the tester navigates to the "Create Your Own Hamper" page**  `step_001` role=setup
    `evt_001`  click      link "Hampers"  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+ResolveURL%28%24u…  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getProductsByUrlK…  -> 200 POST https://cfaxieb3i5-dsn.algolia.net/1/indexes/prod_fm_en_gb_cms_conten…  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+ResolveURL%28%24u…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getMegamenu%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getBanners%7Bbann…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getStoreConfigDat…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+GET_CURRENCIES%7B…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCart%28%24cart…  -> 200 POST https://cfaxieb3i5-dsn.algolia.net/1/indexes/*/queries?x-algolia-agen…  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getProductDetailF…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+GetCategoryList%2…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+checkUserIsAuthed…  [console error] Uncaught [object Object]
    `evt_002`  click      button "Start Creating Your Own Hamper"  -> 200 POST https://api.fortnumandmason.com/nrapi/ipcountry  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…
    `evt_003`  click      generic ""
    `evt_004`  click      option "Morocco"
    `evt_005`  click      button "Continue"  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…
    `evt_006`  click      generic ""  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getProductStock%2…
    `evt_007`  click      button "Continue"  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCart%28%24cart…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getCmsBlock%28%24…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getExportGroups%2…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+GetCategories%28%…  -> 200 POST https://cfaxieb3i5-dsn.algolia.net/1/indexes/*/queries?x-algolia-agen…  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getExportGroups%2…

**When the tester adds items to the "Small Wicker Basket" until it reaches capacity**  `step_002` role=test_step
    `evt_008`  click      button "Add to Hamper"
    `evt_009`  click      button "Increase Quantity"
    `evt_010`  click      button "Increase Quantity"
    `evt_011`  click      button "Increase Quantity"
    `evt_012`  click      button "Increase Quantity"
    `evt_013`  click      button "Increase Quantity"
    `evt_014`  click      generic ""
    `evt_015`  click      generic ""  (rapid_sequence)
    `evt_016`  click      button "Increase Quantity"

**And the tester increases the quantity of items until the hamper upgrades to a "Medium Wicker Basket"**  `step_003` role=test_step
    `evt_017`  click      button "Upgrade"  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getProductStock%2…
    `evt_018`  click      button "Increase Quantity"
    `evt_019`  click      button "Increase Quantity"
    `evt_020`  click      button "Increase Quantity"
    `evt_021`  click      button "Increase Quantity"
    `evt_022`  click      button "Increase Quantity"
    `evt_023`  click      button "Increase Quantity"
    `evt_024`  click      button "Increase Quantity"
    **Then** the hamper is shown as a "Medium Wicker Basket"
        evidence: "Medium Wicker Basket"  (semantic_node via `tc_0001` at `evt_024`)  provenance=objective

**Omitted from this scenario, on purpose:**

- abandoned: tester clicked cancel after reaching the maximum hamper size `evt_034`

### Scenario: A hamper automatically upgrades to a Large Wicker Basket when capacity is reached  *(kind: test_case)*

tags: @hampers

**When the tester increases the item quantity until the "Large Wicker Basket" upgrade is triggered**  `step_004` role=test_step
    `evt_025`  click      button "Increase Quantity"
    `evt_026`  click      generic ""
    `evt_027`  click      button "Increase Quantity"
    `evt_028`  click      button "Upgrade"  -> 200 GET https://www.fortnumandmason.com/graphql?query=query+getProductStock%2…
    `evt_029`  click      button "Increase Quantity"
    `evt_030`  click      button "Increase Quantity"
    `evt_031`  click      button "Increase Quantity"
    `evt_032`  click      button "Increase Quantity"
    `evt_033`  click      button "Increase Quantity"
    **Then** the hamper is shown as a "Large Wicker Basket"
        evidence: "Large Wicker Basket"  (semantic_node via `tc_0002` at `evt_029`)  provenance=objective

---

## 4 · Proposed and refused

*Nothing was proposed and refused.*

---

## 5 · What the gate said

**Rejections:** none

**Warnings:** none

**Critic findings:**

- `step_name` on `scenario` — 
- `step_name` on `scenario` — 
- `step_name` on `scenario` — 

| metric | value |
|---|---|
| assertions accepted | `2` |
| grounding rate | `1.0` |
| validator pass (first) | `1.0` |
| validator pass (final) | `1.0` |
| critic findings raised / resolved | `3 / 3` |
| repair attempts | `3` |
| tool calls total | `4` |
| tool calls per step | `{'step_003': 0, 'step_004': 0, 'step_002': 0}` |

**Splitter:** `{"decisions": [{"scenario": "Hamper size upgrades automatically when capacity is reached", "stepIds": ["step_001", "step_002", "step_003", "step_004"], "trigger": "33 events in one scenario, over the floor of 12", "groups": [{"name": "A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached", "stepIds": ["step_001", "step_002", "step_003"]}, {"name": "A hamper automatically upgrades to a Large Wicker Basket when capacity is reached", "stepIds": ["step_004"]}]}], "scenariosAdded": 1}`

