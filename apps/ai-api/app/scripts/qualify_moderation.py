"""`python -m app.scripts.qualify_moderation` — TG-M5.2's command, kept as an alias of
`python -m app.scripts.qualification --task moderation`
(`specs/011-tg-m5-3-attention-judgement/contracts/qualification.md` version 2 §1, D-TG-194).

Its flags are version 1's, unchanged: `--profile`, `--prompt`, `--fixtures-dir`, `--repeat`. The
moderation suite keeps 010's advert gates (Q5-Q7) with repeat, errors and tracked lines (Q8, Q11,
Q12); version 1's attention gates moved to the attention suite (A1-A9). Everything lives in
`app/scripts/qualification/`; this module only names the task.
"""

from __future__ import annotations

import sys

from app.scripts.qualification.__main__ import main as qualification_main


def main() -> None:
    qualification_main(["--task", "moderation", *sys.argv[1:]])


if __name__ == "__main__":
    main()
