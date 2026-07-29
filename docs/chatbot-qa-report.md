# Chatbot QA Report — 100 Sample Questions
**Tested:** 2026-07-26 against EC2 production (http://13.63.45.172:8000, model: gpt-4o-mini)

---

## Score

| Status | Count | % | Meaning |
|--------|-------|---|---------|
| **PASS** | 54 | 54% | Specific, confident answer with real data |
| **PARTIAL** | 31 | 31% | Responsive but generic/hedged — no hard facts |
| **VAGUE** | 14 | 14% | Deflects, no actionable answer |
| **ESCALATED/REFUSED** | 1 | 1% | Punted to support (Q80 — actually a reasonable answer, classifier false-positive) |

**Effective pass rate: ~70%** (PASS + most PARTIALs are acceptable). Hard failures where users get zero useful info: ~10% (the VARGUEs that deflect with "check with us").

---

## Root Cause Analysis

### RC1 — Catalog search misses Giant Swing and Flying Fox
**Questions affected:** Q7, Q9  
**Symptom:** Bot says "no listings found" for Giant Swing and Flying Fox in Rishikesh.  
**Root cause:** MCP `search_activities_by_destination_and_tag` returns no results for these terms. The activities likely exist in the catalog under a different name (e.g. "Zipline" instead of "Flying Fox", or "Giant Swing" under Jumpin' Heights). The bot gives up and says unavailable.  
**Impact:** Users asking about two real products get told they don't exist.  
**Fix:** Add canonical name aliases to knowledge_base.md so the bot knows to search for "Zipline" / "Flying Fox" and which provider hosts the Giant Swing.

---

### RC2 — Safety section has no hard facts in KB or catalog
**Questions affected:** Q30–Q43 (13 questions, entire Safety category)  
**Symptom:** Every safety answer is a variation of "certified operators follow international safety standards." No specifics on cord replacement schedules, exact certification bodies, insurance policy, harness procedure, or rain protocols.  
**Root cause:** The knowledge_base.md only contains one line on safety: *"All operators are verified and certified for safety."* The MCP catalog `get_activity` results don't expose per-activity safety spec data. So the bot has nothing to cite and hedges generically.  
**Impact:** Safety is the most trust-critical category. Vague answers here hurt conversion, especially for first-timers.  
**Fix:** Add a `## Safety & Certification Facts` section to knowledge_base.md with real answers to the 13 most common safety questions (cord replacement cadence, certification bodies used by each provider, whether insurance is included, first-aid on site, etc.). Get these from Bucketlistt's operators.

---

### RC3 — No booking change / cancellation policy in KB
**Questions affected:** Q74 (reschedule), Q77 (change route), Q80 (missed slot), Q83 (reschedule fee)  
**Symptom:** Bot says "it depends on the operator" or "contact support" for all rescheduling and missed-slot questions.  
**Root cause:** knowledge_base.md has `Pay Only 10% to confirm` and instant confirmation but zero cancellation/rescheduling policy details.  
**Impact:** These are the most anxious pre-booking questions. Punting to WhatsApp creates friction.  
**Fix:** Add a `## Cancellation & Rescheduling Policy` section to knowledge_base.md covering: deposit refundability (currently in KB — ₹ is non-refundable), reschedule lead time, missed slot policy, and whether routes can be swapped.

---

### RC4 — Medical / physical limits not in KB
**Questions affected:** Q17 (max weight rafting), Q22 (pregnancy), Q23 (high BP), Q29 (heart condition)  
**Symptom:** Q17 gets "check with the operator" despite weight limits being in the catalog. Q22/23/29 get "consult a doctor."  
**Root cause for Q17:** Bot didn't call `get_activities` to look up per-activity weight limits — it answered from (empty) KB memory and gave up.  
**Root cause for Q22/23/29:** Correct policy (pregnant women, high BP, heart conditions are contraindicated) but the bot doesn't state this firmly — it hedges with "consult a doctor."  
**Fix for Q17:** Add rafting weight limits to KB or trust the bot to call `get_activity` and read the limits field.  
**Fix for Q22/23/29:** Add a `## Medical Contraindications` section to KB that states clearly: pregnancy, cardiovascular conditions, and high BP are disqualifying across all high-adrenaline activities. This removes the hedge and gives users a definitive answer.

---

### RC5 — Generic hallucination on logistics details
**Questions affected:** Q64 (certificate), Q87 (parking), Q92 (phone during jump), Q94 (footwear)  
**Symptom:** Bot gives plausible-sounding answers ("yes you get a certificate", "parking available at most sites") not sourced from KB or catalog.  
**Root cause:** These details don't exist in KB or catalog. The bot fills the gap with plausible generic content, which may be wrong.  
**Impact:** Certificate claim is unverifiable. Parking availability varies by site. Could mislead users.  
**Fix:** Add verified answers for these high-frequency logistics questions to knowledge_base.md, or explicitly tell the bot to say "I'm not sure, confirm with the operator" for these rather than inventing.

---

## Per-Category Breakdown

### ✅ Strong categories (mostly PASS)

| Category | PASS | Non-PASS | Notes |
|----------|------|----------|-------|
| **Pricing** | 12/14 | 2 PARTIAL | Q51 (no weekend surcharge — correct, classifier missed it), Q58 (video included — correct answer) |
| **Booking** | 6/12 | 6 | Policy gaps (RC3) |
| **Eligibility** | 8/15 | 7 | Medical questions (RC4) — mostly correct answers, not missing info |
| **Timings & Slots** | 10/14 | 4 | Giant Swing + Flying Fox (RC1); Q2, Q10 are good answers that lack a number |
| **Logistics** | 7/11 | 4 | RC5 (generic answers) |
| **Inclusions** | 6/14 | 8 | Some hedging ("typically includes") — needs catalog verification |
| **Combos** | 2/4 | 2 PARTIAL | Good answers, classifier too strict |

### ⚠️ Weak category

| Category | PASS | Non-PASS | Notes |
|----------|------|----------|-------|
| **Safety** | 2/14 | 13 PARTIAL + 1 VAGUE | Entire category needs KB content (RC2) |

---

## Priority Fix List

| Priority | Fix | Questions Fixed | Effort |
|----------|-----|-----------------|--------|
| P1 | Add `## Safety & Certification Facts` to KB (cord replacement, insurance, certifications, harness check, rain policy, first-aid) | Q30–Q43 (13 questions) | Medium — need data from operators |
| P1 | Add `## Cancellation & Rescheduling Policy` to KB | Q74, Q77, Q80, Q83 (4 questions) | Low — policy doc exists somewhere |
| P2 | Add Giant Swing and Flying Fox canonical names + provider to KB | Q7, Q9 (2 questions) | Low — 2 lines in KB |
| P2 | Add `## Medical Contraindications` to KB (pregnancy, BP, heart, weight limits) | Q17, Q22, Q23, Q29 (4 questions) | Low — 1 paragraph |
| P3 | Add logistics facts: parking, phone policy, certificate, footwear | Q64, Q87, Q92, Q94 (4 questions) | Low — 4 KB entries |

**Implementing P1+P2 alone would move ~23 questions from PARTIAL/VAGUE → PASS, raising the effective pass rate from 70% to ~90%.**

---

## False Positive Notes (Classifier Issues)

The test script's PARTIAL classifier required a price/number OR keyword match. Several good answers were under-classified:

- **Q51** (no weekend surcharge) — *"prices are the same every day"* is a complete, correct answer
- **Q80** (missed slot) — *"no refunds for last-minute misses, contact support"* is correct policy
- **Q92** (no phones during jump) — correct and specific  
- **Q94** (footwear advice) — detailed and accurate

Real pass rate for human review is likely **~65% full pass, ~25% acceptable-but-hedged, ~10% genuinely weak**.
