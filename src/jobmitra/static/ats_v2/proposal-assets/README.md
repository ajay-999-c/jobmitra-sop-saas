# Proposal typography and logos

## Approved single-page terms template

The renderer uses the unchanged `word/media/image1.png` from
`docs/references/proposal-terms/approved-single-page.docx`, copied as
`terms-logo.png` (SHA-256
`1c4d5db28c38ffda41331557d0cb312ece95f1515b2bd22883a86aeddf974f6f`).
The source DOCX specifies Arial; its approved PDF embeds Liberation Sans.

`LiberationSans-Regular.ttf` and `LiberationSans-Bold.ttf` are unchanged font
files from the official Liberation Fonts 2.1.5 release:
https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5

Upstream binary archive:
https://github.com/liberationfonts/liberation-fonts/files/7261482/liberation-fonts-ttf-2.1.5.tar.gz

Archive SHA-256: `7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0`.
Regular SHA-256: `76d04c18ea243f426b7de1f3ad208e927008f961dc5945e5aad352d0dfde8ee8`.
Bold SHA-256: `788abee4c806d660e8aee46689dd8540cd4bb98da03dcc9d171ce3efd99a9173`.

The upstream SIL Open Font License 1.1 and copyright notices are retained in
`OFL-Liberation.txt`; the font files are not renamed or modified. These bundled
assets require no system-font installation, runtime download or added package
dependency on either Windows or macOS.

## Retained historical two-page assets

The logo is the exact `word/media/image1.jpg` from the unchanged finalized proposal DOCX, whose SHA-256 is `c4a162bc30c816c8ee648cb5ac68d38c22134d4d94830c148a05d3a97d78cc35`. Existing shared branding assets remain unchanged.

The proposal-only font faces use Inter 4.1 outlines from the official author source:
https://raw.githubusercontent.com/rsms/inter/v4.1/docs/font-files/InterVariable.ttf

Original font SHA-256: `4989b125924991b90d05b2d16e0e388c48f7d5bb8b30539bbf9c755278d0ccaf`.

Static instances were produced with FontTools at optical size 14 and weights 400/700. Font family and PostScript names were changed to Jobmitra Proposal / JobmitraProposal-Regular / JobmitraProposal-Bold to respect the Inter reserved font name. Copyright/license records remain; see OFL-Inter.txt. Bundled TTFs require no runtime download or added application dependency.
