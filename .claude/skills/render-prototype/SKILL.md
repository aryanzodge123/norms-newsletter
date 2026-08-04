---
name: render-prototype
description: Render the committed Claude Design app prototype in a browser and screenshot its screens. Serves prototypes/ over HTTP, walks App Interface and App Onboarding, and captures each screen. Use when a newer export lands in prototypes/ and you need to see what changed, or any time someone asks to look at the app prototype rather than read it.
---

# render-prototype

Renders the app prototype in `prototypes/` and captures its screens.

`prototypes/README.md` is the reference for what the export contains and why it
needs a server. This skill is the procedure: serve, verify, walk, capture,
clean up. Read the README first if you have not.

**Read before you render.** The export's own advice, repeated in
`prototypes/README.md`, is that dimensions, colors and layout rules are all
literal constants in the source, so reading the HTML answers most questions
faster than a screenshot does. Render when the question is about motion,
state, or how screens sequence, or when someone wants to look at it.

## 1. Preflight the browser

Do this first. A session with no connected Chrome should route to the fallback
immediately, not after a server is running and a tab is open.

Load `mcp__claude-in-chrome__list_connected_browsers` and call it.

- **One browser returned.** Continue.
- **More than one.** Ask which to use with `AskUserQuestion`, listing every
  browser by name with its `deviceId`, then call `select_browser`. Do not pick
  one yourself.
- **Empty list, or the tools are not available at all.** Chrome is not
  connected. Ask the user whether they have Chrome and want to set it up, using
  `AskUserQuestion` with these options: set it up now, or continue by reading
  the source. If they choose to read, go to the fallback at the end of this
  skill and do not start the server.

### Setting up Claude in Chrome

Show this when the user wants to set it up. Verified against
`code.claude.com/docs/en/chrome`.

Requirements:

- Chrome, Edge, or another Chromium browser such as Brave, Arc, Vivaldi or
  Opera. Not supported under WSL.
- The Claude in Chrome extension, version 1.0.36 or higher, from the Chrome
  Web Store.
- A direct Anthropic plan: Pro, Max, Team or Enterprise. Not available through
  Bedrock, Vertex or Foundry.
- Signed in with `/login`. An API key or a `claude setup-token` credential
  keeps the integration off, because the extension cannot authenticate with
  those.

Steps:

1. Install the extension from the Chrome Web Store and sign in with the same
   Claude account.
2. Start Claude Code with `claude --chrome`, or run `/chrome` in a running
   session.
3. Run `/chrome` to confirm. It is working when the panel shows
   `Status: Enabled` and `Extension: Installed`.
4. To avoid the flag every session, run `/chrome` and choose
   **Enabled by default**. Note this loads browser tools into every session and
   so increases context use. Leave it off and use `--chrome` if that matters.

If the extension is installed but not detected, restart Chrome. The native
messaging host config is read at browser startup. Then `/chrome` and
**Reconnect extension**. On a long session the extension service worker can go
idle and drop the connection, which the same reconnect fixes.

Site permissions are inherited from the extension, so grant `localhost` there
if a browser action stalls waiting for approval.

## 2. Serve

```bash
python3 -m http.server 8055 --directory prototypes
```

Run it in the background. `http.server` answers GET and HEAD only, so it
cannot write to what it serves.

Confirm four things return 200 before opening a browser. The fourth is the
runtime dependency and fails first when the network is restricted:

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8055/App%20Interface.dc.html" \
  "http://localhost:8055/norm-editions.js" \
  "http://localhost:8055/support.js" \
  "https://unpkg.com/react@18.3.1/umd/react.production.min.js"
```

## 3. Open

Load the tools in one `ToolSearch` call, not one per tool:

```
select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__read_console_messages,mcp__claude-in-chrome__resize_window
```

Call `tabs_context_mcp` first, work in a new tab, then navigate to
`http://localhost:8055/App%20Interface.dc.html`.

**Size the window before capturing anything.** The phone frame is 402x874 CSS
px. Resize to about 560x1000, then screenshot and check the image comes back
near 614x823. `resize_window` can report success without applying. If the
screenshot is very wide and short, around 1568x536, it did not apply. Call it
again. Every capture taken in that state is an unreadable downscale.

## 4. Verify the data loaded

This is the step that makes the render trustworthy, and it is easy to skip
because a failed load still looks correct.

Open `prototypes/norm-editions.js` and read the first entry's `noLabel` and
`dateLong`. The masthead must match it, and the Archive tab must show the full
edition count. Anything older, or placeholder text, means the dynamic module
import failed and the server step did not take effect.

Also check the console for `dc-runtime: window.React is not available yet`,
which means the unpkg fetch was blocked.

## 5. Walk and capture

Screenshot with `save_to_disk: true`. Chain click, wait and screenshot through
`browser_batch` rather than one call each.

Take a screenshot and read coordinates off it each time. Do not carry
coordinates over from a previous run: layout shifts between exports.

`App Interface`

- the three tabs: Today, Archive, More
- a story opened into the pushed reader. Use a `Read the full story` link on a
  story card. The headline itself is not tappable.
- Norm chat, opened from the round mug button, and its past-chats list behind
  the `Past chats` toggle
- the docked mini-player and the in-app browser
- the dark toggle, labelled `Night paper`, under More

`App Onboarding`

- the intro slides
- the step flow: name, topics, delivery, plan. On the topics step capture the
  minimum-selection counter and the disabled call to action.

## 6. Finish

Copy the captures into the session scratchpad under ordered names such as
`01-today.jpg`, then send them. The Chrome temp directory is not durable.

Stop the server. A non-zero exit from the background task is the kill signal,
not a failure.

## Reporting

Report what changed against the previous export, using `github.md` and what is
on screen. Note anything that appears in the prototype but is listed under
"What the prototype shows that v1 will not ship" in `prototypes/README.md`, so
a deferred feature is never mistaken for a new one.

The prototype governs nothing. If something here disagrees with SPEC.md,
SPEC.md wins, and under CLAUDE.md rule 1 an unspecified screen needs an
approved spec addition before any code.

## Fallback without browser tools

Read the source. Each `.dc.html` is one file: a `<style>` block, markup using
`sc-if`, `sc-for` and `{{ }}` bindings, and a `DCLogic` class holding the state
and the render values. State shapes and data contracts are literal constants
near the top of the class. This is how APP-ARCHITECTURE.md section 15b was
written.
