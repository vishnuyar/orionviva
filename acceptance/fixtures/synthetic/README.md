# Synthetic acceptance fixtures

This directory is reserved for deliberately fictional documents used to make
acceptance runs repeatable and safe to share.

A committed fixture must:

- describe only invented people, institutions, employers, merchants, account
  identifiers, addresses, and financial values;
- avoid copying the layout, branding, or text of a real person's document;
- include an answer key only when the scenario needs an objective comparison;
- cover one declared behavior or edge case without teaching classification code
  about a specific institution;
- be reviewed for accidental personal information before commit; and
- carry a nearby note explaining which test identifiers use it.

Do not anonymize a real statement and call it synthetic. Create the document
from fictional facts. Real and merely redacted inputs remain local private test
data and never belong here.

