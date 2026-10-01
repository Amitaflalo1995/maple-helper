<p align="center">
  <img src="assets/brand/wordmark.png" width="320" alt="Maple Helper">
</p>

<p align="center"><b>Your personal Maple Story Classic World assistant</b></p>

<p align="center"><sub>Unofficial companion for Maple Story Classic World · Not affiliated with Nexon</sub></p>

<p align="center">
  <a href="https://github.com/Amitaflalo1995/maple-helper/releases/latest"><img src="https://img.shields.io/badge/Download-Windows%20installer-2ea44f?style=for-the-badge&logo=windows&logoColor=white" alt="Download the Windows installer"></a>
  <a href="https://github.com/Amitaflalo1995/maple-helper/releases"><img src="https://img.shields.io/badge/All-releases-555?style=for-the-badge&logo=github&logoColor=white" alt="All releases"></a>
</p>

<p align="center">
  <a href="https://github.com/Amitaflalo1995/maple-helper/releases/latest"><img src="https://img.shields.io/github/v/release/Amitaflalo1995/maple-helper?label=latest&sort=semver" alt="Latest release"></a>
  <a href="https://github.com/Amitaflalo1995/maple-helper/releases"><img src="https://img.shields.io/github/downloads/Amitaflalo1995/maple-helper/total" alt="Total downloads"></a>
</p>

## About

Maple Helper is a Windows desktop assistant that puts a transparent chat overlay on top of Maple Story Classic World. Press **F9** to open it, then type a question or hold **F10** to speak. Answers draw on a screenshot of your game, your character profile, previous conversations, and a local copy of the NiaMeowDB game database.

Use it to look up drops, find quest NPCs, or ask where to train without switching away from the game.

## Features

- **In-game chat:** Open and close the overlay with a global hotkey.
- **Screen context:** Capture the game window when you open the overlay, with a camera button to refresh the screenshot.
- **Character profiles:** Track your level, job, map, and active quests, with updates based on your conversations and screenshots.
- **Conversation memory:** Keep separate chat history and session summaries for each character.
- **Visual reference cards:** See images of relevant monsters, items, maps, NPCs, and quests alongside answers.
- **Hebrew and English:** Use either language, including mixed text with English game names.
- **Local speech recognition:** Transcribe voice input on your computer using ivrit.ai Whisper models.

The app uses screen capture and its own overlay window. It does not read game memory, inject input, or automate gameplay.

## Requirements

- Windows 10 or 11.
- Python 3.10 or later to run from source.
- Claude Code installed, with either a Claude Pro or Max account or an Anthropic API key. The app uses Claude Code in both modes.
- Maple Story Classic World running in **Borderless** or **Windowed Fullscreen** mode.
- An internet connection for Claude responses and initial data downloads.
- A microphone if you want to use voice input.

## Install

Download the latest release from the [Releases page](https://github.com/Amitaflalo1995/maple-helper/releases/latest):

- **`MapleHelper-Setup-<version>.exe`**: the installer. This is the recommended option and doesn't need admin rights.
- **`MapleHelper-<version>-portable.zip`**: unzip it anywhere and run `MapleHelper.exe`.

Both include the knowledge base. The app tells you when a new version is available.

## Run from source

Open PowerShell in the repository folder.

1. Create a virtual environment and install the dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements.txt
   ```

2. Download the knowledge base:

   ```powershell
   .\.venv\Scripts\python tools\scrape_meowdb.py
   ```

   This saves game data and images to `data/kb/`. The initial download can take a while. If interrupted, run the command again to resume.

3. Start the app:

   ```powershell
   .\.venv\Scripts\python -m maplehelper
   ```

4. Follow the setup screens to choose a language, connect Claude, and create your character profile. The setup includes options to install Claude Code and sign in, or enter an Anthropic API key.

## Using the overlay

| Control | Action |
| --- | --- |
| **F9** | Open or close the chat overlay. |
| **F10** (hold) | Record your voice. Release to transcribe and, by default, send the question. |
| **Esc** | Close the overlay. |
| **Camera button** | Take a fresh screenshot of the game window. |
| **System tray menu** | Show the overlay, open settings, or quit the app. |

In settings, you can change the hotkeys, language, opacity, font size, answer length, and whether voice questions are sent immediately.

The speech model downloads on first use, so the first voice request takes longer. Transcription uses CUDA when available and falls back to the CPU.

## Data and privacy

Settings, character profiles, conversation history, speech models, and downloaded knowledge-base updates are stored locally in `%APPDATA%\MapleHelper`. The knowledge base built from source is stored in `data/kb/` inside the repository. API keys entered in the app are stored in Windows Credential Manager.

When you ask a question, the app sends Claude your question, the available game screenshot, character profile, recent conversation, earlier session summaries, and relevant knowledge-base context. Claude can also read local knowledge-base files to answer the question. After a chat session has been closed for 30 minutes, the app may send the session transcript to Claude to generate a summary for future conversations.

Voice recordings are transcribed locally. The resulting text is used as your question. The app also checks GitHub Releases for knowledge-base updates.

## Development

Install the test runner and run the Hebrew and English text-rendering tests:

```powershell
.\.venv\Scripts\python -m pip install pytest
.\.venv\Scripts\python -m pytest tests -q
```

For a small knowledge-base download during development, limit the scraper to five pages per category:

```powershell
.\.venv\Scripts\python tools\scrape_meowdb.py --limit 5
```

## Credits

- Game data and images: [NiaMeowDB](https://meowdb.com), used with permission. Game assets belong to their rights holders.
- Font: [Rubik](https://fonts.google.com/specimen/Rubik), distributed under the [SIL Open Font License](assets/fonts/OFL.txt).
- Speech recognition: [ivrit.ai](https://huggingface.co/ivrit-ai) Whisper models.
- Maple Story Classic World is a trademark of Nexon. This project is not affiliated with or endorsed by Nexon.
