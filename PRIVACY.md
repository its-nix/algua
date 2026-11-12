# Algua — privacy note for the "Algua" Google app

The "Algua" Google OAuth app exists so that this project's own software can keep its research
notes in its owner's Google Drive. It has exactly one user: the owner of this project.

- **What it can access:** only files the app itself created in the owner's Drive (Google's
  `drive.file` permission). It cannot see, read or change any other file in the account.
- **What it stores there:** research-ideation spreadsheets — an inbox of ideas, a list of research
  categories and sources, inspiration notes and a summary of tested ideas. No trading account
  data, credentials or personal information about anyone else.
- **Where data goes:** nowhere else. The app does not sell, share or transfer data to third
  parties, and does not use it for advertising. Data is read and written only by the owner's own
  Algua installation.
- **Revoking access:** the owner can remove the app at any time from
  <https://myaccount.google.com/permissions>; the files it created stay in their Drive.

How the integration works: [docs/agent/drive.md](docs/agent/drive.md).
Questions: open an issue in this repository.
