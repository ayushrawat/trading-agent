# Built in an Evening with Claude Code

Shipping a personal day-trading dashboard from *"I want to share this with a few friends"* to *live, authenticated, on a fixed HTTPS URL, surviving reboots* — in roughly **2 hours**. The split was instructive.

## Time Spent

| | Minutes |
|---|---|
| Oracle Cloud signup (rejected by their fraud system) | 45 |
| Fly.io account unlock + card on file | 25 |
| Google OAuth client + consent screen + test users | 20 |
| **— config / onboarding —** | **~90** |
| Hit-rate backtest + LLM prompt rework (actual product work) | 25 |
| `fly deploy` (image build + push + verify) | 5 |
| **— code / ship —** | **~30** |

About 75% of an evening went to cloud-onboarding friction. Worth filing away for next time.

## The Path

Started on **Oracle Cloud Always Free** — the always-on, $0-forever dream. Made it through the signup form, card accepted, then hit the silent *"an error occurred while creating your account"* page. Oracle's fraud heuristics reject a large share of Indian signups regardless of input correctness. Bailed after 45 minutes.

Pivoted to **Fly.io**: ~$4/month, single machine in `bom` (Mumbai), `shared-cpu-1x` @ 512 MB with a 1 GB SQLite volume, always-on because the in-process scheduler has to keep firing on a 15/30/60-min cadence. Fly flagged the account as "high risk" on first attempt — standard for new Indian accounts — but a brief manual review unlocked it within the hour. Auth is **Google OAuth + a manually-curated email allowlist** in Fly secrets; managing access takes 30 seconds per user (add to Google test users + update one Fly secret).

## What Actually Got Built

In the same session, on top of the existing rule-engine + news + LLM pipeline:

- **Per-stock backtest.** Every suggestion now ships with a "Hit rate: 58% (n=24)" tile, computed by replaying the same rule combo over the past year on the same stock and counting target-before-stop within a 5-day window. Pessimistic on intra-bar collisions (stop wins ties). Unresolved signals are excluded from the sample. Honesty over false confidence.
- **Off-radar bias.** The LLM prompt now explicitly deprioritizes the 20 most-covered NIFTY names (RELIANCE, TCS, HDFCBANK, …) unless their setup is exceptional. First run with the new prompt dropped from 10 suggestions to 3 — the LLM got more skeptical and more willing to surface less-obvious ideas, which was the point.
- **Idempotent SQLite migration.** Two new columns on the deployed volume without losing the existing data.

## The Claude Code Bit

Every cloud command, every code edit, every commit happened in pair with Claude Code. Specifically, what the model handled cleanly that's easy to get wrong by hand:

- `fly secrets set` with six values in one call, generating a 48-byte URL-safe session secret inline.
- The SQLite `ALTER TABLE ADD COLUMN` migration on startup, with an introspection check so it's safe to run repeatedly.
- Refactoring the signal logic so the live evaluator and the backtest share the *same* `_vote_at()` helper — backtest hit-rates can't drift from live behavior, by construction.
- Catching that `auto_stop_machines = "off"` + `min_machines_running = 1` were required for the in-process scheduler. The `fly.toml` from an earlier template had auto-stop on; for a scheduler-driven app that silently breaks freshness.

I made the **decisions** — universe size, indicator weights, allowlist policy, when to ship vs. wait, what "foolproof" honestly meant. The model executed, surfaced trade-offs I'd missed, and stopped me from pasting an OAuth secret into a Caddy config when we briefly thought we'd self-host.

## The Prompts (What I Actually Asked For)

The model did the typing, but the direction came from these. Lightly annotated, original phrasing kept.

**The goal, no plan attached:**

> ok - time to publish to somewhere from where i can share to some people i want to have access to - and it is up all the time

**Scope-setting on the README:**

> also modify the readme so that it only shows how it works but doesn't show how to run or deploy none of that - just explanation of what is done

**Course-correction when the proposed plan (Fly.io) didn't feel right at first:**

> no wait - fly.io is actually costly - do you have any other suggestions

**Pushed back again after reading Fly's pricing page myself:**

> so i went through the fly.io pricing plans and it is not what you're suggesting - it goes by the usage and the moment i start to do some processing - it's gonna charge me like hell

**Decision, once the model laid out actual numbers for this workload (~$4/mo, flat):**

> ok no - let's go fly io

**Feature ask — included a request ("full proof") that needed calibration:**

> i want to make sure this app also suggests BSE stocks - and also looks at past data for last year or so before making the suggestions - like full proof suggestions suggested by an LLM

**Refined after the model pushed back on "foolproof" and unpacked what "BSE" really meant:**

> c - like suggestions that might not be on popular radars; i understand about the foolproof - but to the best we can - like lets start with hit rates initially

**Shipping discipline — validate one phase before doubling down:**

> let's stay at phase 1 for now

## What I'd Do Differently

- **Skip Oracle.** Saving $2–4/month doesn't compensate for an hour fighting fraud heuristics. Fly first.
- **Sign up for Fly *before* a deadline.** The high-risk review queue is fine when you're not in a hurry.
