# Where Vera can still compete (researched Oct 30, 2026)

The Nebius × NVIDIA hackathon closed on Oct 30, 2026 at 10:00 PDT before Vera was submitted. This is the
shortlist of open events that fit Vera, checked against each event's own rules page.

## Recommended

| Event | Deadline | Prize | Why it fits | Deal-breakers checked |
|---|---|---|---|---|
| **[Arbiter Hacks V1](https://arbiter-hacks-v1.devpost.com/)**, General track | **Dec 20, 2026, 9:00 pm PST** (Dec 21, 10:30 IST) | $7,800 total; 1st General $2,100 + credits | Any stack, any idea. Scored on technical execution 35%, innovation 25%, completeness and polish 25%, demo 15%: Vera's strengths | Teams 1–4, solo allowed; no "new projects only" clause on the rules page; repo and video required; late submissions not judged |
| **[Codegeist 2026](https://codegeist2026.devpost.com/)** (Atlassian), stretch | Dec 22, 2026, 12:00 pm PST | $120K pool; $1,500 bonus awards (e.g. Best Agents, Rovo) | Existing projects are allowed if rebuilt on Forge. Pitch: Vera as a Rovo agent that turns a tester export attached to a Jira issue into non-conformance tickets per bad cell, plus a Confluence QC report | Must be a Forge app (Node/TS) with an installation link for judges; Vera's Python engine runs as an external service. Free Atlassian developer account. Video under 5 min |

Arbiter's Theme track ("Rethinking Waste") is arguable (scrapped good cells and defective cells shipped into packs
are both waste), but its judges check that waste is the *primary* purpose. General track is the safer pick.

## Checked and ruled out

| Event | Reason |
|---|---|
| [Kiroween 2026](https://kiroween.devpost.com/rules) | New projects only (started on or after Oct 30, 2026) and must be built with Kiro |
| [HackWithAditya](https://hackwithaditya.devpost.com/rules) | Accepts existing prototypes, but needs 4–6 college students and an on-campus finale |
| [EV Battery Intelligence Challenge](https://evbic.vlsisystemdesign.com/) | Ended March 2026; hardware (RISC-V board) based |
| [AI Powered Battery Fitness Assessment](https://battery-challenge.vercel.app/) | About a "battery" of sports fitness tests, not cells |
| Google Gemini and NVIDIA-run hackathons | None open (all 2026 editions closed) |
| Youth4Climate Services Innovation Hackathon | In person in Nairobi |

## Model access without a card

Neither recommended event requires Nebius. Vera's LLM layer speaks the OpenAI-compatible API, so it can call **NVIDIA
Nemotron through NVIDIA's own API** (`https://integrate.api.nvidia.com/v1`, keys start with `nvapi-`). Several third-party
guides say build.nvidia.com gives free trial credits with no card and about 40 requests/min per model; this is not
confirmed on an official NVIDIA page, so confirm on sign-up. Nebius Token Factory stays supported if a card becomes
available.
