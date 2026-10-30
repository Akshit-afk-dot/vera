# Demo video script (under 3 minutes)

Record the screen of the live demo (https://akshit-afk-dot.github.io/vera/) at 1080p with your voice. No music.
Rules for most hackathons: under 3 minutes, public on YouTube, no third-party trademarks or copyrighted music.

| Time | Screen | Say (roughly) |
|---|---|---|
| 0:00 | Home page, scroll the hero slowly | "Every lithium-ion cell is charged and measured after assembly, on testers that run hundreds of cells at once. Every tester exports a different file layout, faults are subtle, and a wrong call costs money either way. This is Vera." |
| 0:20 | Open the semicolon-CSV run; let the replay start | "Here's a 128-channel export Vera has never seen: semicolon separators, decimal commas, millivolts. Vera peeks at its structure, and NVIDIA Nemotron writes the code to read it." |
| 0:40 | Expand the generated code; point at the sandbox result and the checks | "The code runs in isolation, and code (not the model) checks the result: units, current sign, time order, cycles." |
| 0:55 | If the run shows a repair, point at the failed check and the repair | "When a check fails, the model gets the failure and repairs its own code." |
| 1:10 | Click "Skip to results"; Batch tab, tray heatmap | "Every number from here on is computed by code: capacity, efficiency, resistance, curve shape, then grades. Each colour is a cell on the tray." |
| 1:30 | Click a flagged cell; Channel tab with curves and evidence | "Here's a flagged cell: what was measured, against the batch median, by which rule. The explanation is written by Nemotron, and every number in it is checked against the results." |
| 1:55 | Report tab; scroll to "How these numbers were produced" | "The report says what was verified. A sentence with a number that isn't in the results is rejected." |
| 2:10 | Thresholds tab: raise grade A to 99.5% and click Regrade | "Grades are bins, not model opinions. Change them and the batch regrades instantly." |
| 2:25 | Home: open the "same layout, next batch" run, show "Recognised a learned layout" | "And Vera remembers: the next file in the same layout skips the model entirely." |
| 2:40 | Home: the results table | "We measured it: on simulated batches with planted faults, F1 0.95 against 0.60 for a standard z-score. Vera: the cell QC agent that shows its work. Built on NVIDIA Nemotron." |

Tips: record in one take per row and cut together; keep the mouse still while talking; zoom the browser to 110%.
