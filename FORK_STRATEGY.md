# Fork Development & Upstream Sync Strategy

This document defines how we manage and develop our fork of `any-auto-register` (`Alexcsharp17/any-auto-register`). The goal is to allow active development of custom providers and platforms while ensuring we can merge upstream updates from the original author (`lxf746/any-auto-register`) with zero or minimal merge conflicts.

---

## 1. Repository Layout & Remotes

Our repository maintains two remotes:
* `origin`: Our fork (`https://github.com/Alexcsharp17/any-auto-register`) — where we push our changes.
* `upstream`: The original repository (`https://github.com/lxf746/any-auto-register`) — from which we pull updates.

### Setting Up Remotes (One-time)
Inside the `packages/any-auto-register` directory:
```bash
git remote add upstream https://github.com/lxf746/any-auto-register
git fetch upstream
```

---

## 2. Upstream Sync Workflow

To pull updates, bug fixes, and selector updates from the original author:

```bash
# 1. Ensure you are on the main branch of the submodule
git checkout main

# 2. Fetch changes from upstream
git fetch upstream

# 3. Merge upstream changes into our main branch
git merge upstream/main

# 4. Resolve conflicts if any, then push to our fork
git push origin main
```

---

## 3. Safe Customization Rules (Conflict Avoidance)

To ensure that `git merge upstream/main` executes cleanly without conflicts, follow these rules when adding custom functionality:

### Rule 1: No Modifications to Existing Platforms
Do not edit files inside existing platform directories (e.g., `platforms/cursor/`, `platforms/chatgpt/`) unless you are fixing a bug that you intend to submit back upstream.
* If you need a customized version of Cursor registration, copy the folder to `platforms/cursor_harness/` and modify the copy.

### Rule 2: Isolated Custom Platforms
Add all new platforms as isolated directories under `platforms/`.
* Example: `platforms/freemodel/`
* Use clean subclassing of the core classes (`BaseProvider`, `BrowserProvider`, etc.).
* Since the registry automatically discovers platforms by scanning directories (via `providers/registry.py` or dynamic imports in `main.py`), your new platform will be registered automatically without modifying the core codebase.

### Rule 3: Isolated Provider Extensions
For helper services (mailbox providers, captcha solvers, proxies, SMS APIs), do not edit the existing provider files. Instead, add new files inside the respective directories using a distinct suffix:
* Custom Mailbox: `providers/mailbox/proton_harness.py`
* Custom SMS / Telegram pool: `providers/sms/sspanel_harness.py`
* Register them in the local initialization files (`__init__.py`) using clean additions at the bottom.

### Rule 4: Decoupled Database & Event Logs
Do not modify the core database schema or migration scripts of `any-auto-register` to fit our specific SQLite scheme (`provider-bindings.sqlite`).
* Instead, write a post-registration hook or helper (e.g., `tools/harness_notifier.py`).
* Once a registration completes successfully, call this helper to notify our parent `ai-harness` SQLite database / OmniRoute.
* This keeps the database schemas completely independent.

### Rule 5: Keep Configurations Local
* Do not commit local credentials, API tokens, or proxies to `config.json` templates.
* Use a `.env` file at the root of `packages/any-auto-register/` or read configurations from environment variables.
* The `.gitignore` file already prevents local `.env` and `config.custom.json` files from being committed.

---

## 4. Contributing Back Upstream
If you fix a generic bug (e.g., a selector broke on Windsurf or Cursor, or a proxy helper failed to parse a common format):
1. Create a branch from `upstream/main`: `git checkout -b fix/upstream-selector upstream/main`
2. Apply the fix.
3. Push to your fork: `git push origin fix/upstream-selector`
4. Open a Pull Request from your branch to `lxf746/any-auto-register:main`.
5. Once merged upstream, you will get this change cleanly during the next sync.
