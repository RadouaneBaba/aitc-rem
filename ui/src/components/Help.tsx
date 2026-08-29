/**
 * How to USE this, as a page you can reach.
 *
 * It existed as two markdown files in a repository, which is the wrong place
 * for at least one of their two audiences: a tester who never opens a terminal
 * has no route to a markdown file, and "read the README" is not a route.
 *
 * **It opens with a numbered walkthrough naming real controls**, because that
 * is what somebody who has just installed the recorder actually needs -- click
 * this, then this. It used to open with three paragraphs about why an objective
 * matters, which is true, useful, and not what a person is here for on their
 * first visit. The reasoning survives; it moved below the walkthrough, where
 * somebody reads it on their second visit when they want better output.
 *
 * **It is a guide to DOING the task, and deliberately not an explanation of the
 * machine.** It was both for a day, and being both is what made it neither.
 * Everything a reader can only act on from a terminal lives in `docs/HOWTO.md`;
 * everything about why the pipeline is shaped as it is lives in
 * `docs/DESIGN_NOTES.md`.
 *
 * **Written from what actually works, not from the spec.** Parts of this
 * codebase have never run against a real recording, and a how-to written from
 * the design would document features that do not exist. Every button named
 * below is a button that exists.
 */

import { Wordmark } from './Wordmark';

export function Help({ onBack }: { onBack: () => void }) {
  return (
    <div className="help">
      <header>
        <Wordmark />
        <div className="spacer" />
        <button onClick={onBack}>Back to the review</button>
      </header>

      <h1>How to use this</h1>
      <p className="lead">
        You record yourself using the application. The tool writes the test cases. You answer two
        short screens.
      </p>

      <h2>Six steps, start to finish</h2>
      <ol className="walkthrough">
        <li>
          <div>
            <b>Open the recorder.</b> Click the <span className="ui">AITC</span> icon in the Chrome
            toolbar, on the page you want to test.
            <span className="say">
              Not there? Open <code>chrome://extensions</code>, turn on Developer mode, click{' '}
              <b>Load unpacked</b> and choose the <code>extension/dist</code> folder.
            </span>
          </div>
        </li>
        <li>
          <div>
            <b>Say what you are checking.</b> One line in the box. The tool tells you underneath
            whether it is specific enough.
            <span className="say">
              “Check that an order over €500 needs approval” — not “test the checkout page”.
            </span>
          </div>
        </li>
        <li>
          <div>
            <b>Click <span className="ui">Start recording</span></b> — the popup closes and the
            page reloads. Everything you do from here is recorded.
            <span className="say">
              Turn on <span className="ui">Talk while I record</span> first if you want to narrate.
              It is the cheapest way to make the output better.
            </span>
          </div>
        </li>
        <li>
          <div>
            <b>Use the application normally.</b> When you are looking at the thing you came to
            check, open the popup and click{' '}
            <span className="ui">Mark what I&rsquo;m verifying</span>, then click that thing on the
            page.
            <span className="say">
              This is the single most useful button in the product. What you point at becomes the
              expected result, word for word.
            </span>
          </div>
        </li>
        <li>
          <div>
            <b>Click <span className="ui">Stop</span></b> — a page opens showing what was recorded
            and what was hidden. Check it, then click <span className="ui">Send to AITC</span>
          </div>
        </li>
        <li>
          <div>
            <b>Answer <span className="ui">Was that right?</span></b> The tool shows you its guesses
            about what should have happened, over screenshots. Press{' '}
            <span className="ui">Right</span> or <span className="ui">Not right</span>. About a
            minute.
            <span className="say">
              The draft appears here on its own a couple of minutes later.
            </span>
          </div>
        </li>
      </ol>

      <Journey />

      <h2>What the buttons in the popup do</h2>
      <table className="compare">
        <tbody>
          <tr>
            <td>
              <b>Mark what I&rsquo;m verifying</b>
            </td>
            <td>
              Point at the thing you came to check — a banner, a total, a badge. It becomes the
              expected result word for word, instead of the tool guessing which of the changes on
              screen mattered.
            </td>
          </tr>
          <tr>
            <td>
              <b>Checkpoint</b>
            </td>
            <td>Ends the current step here, when the tool would otherwise have run two together.</td>
          </tr>
          <tr>
            <td>
              <b>New scenario</b>
            </td>
            <td>
              A separate test case starts from this point. This is not a suggestion — wherever you
              press it the scenario is cut, and nothing overrules you.
            </td>
          </tr>
          <tr>
            <td>
              <b>Mark a bug</b>
            </td>
            <td>
              Something just went wrong. The test case is written to expect the CORRECT behaviour,
              so it fails on this build — which is the point.
            </td>
          </tr>
          <tr>
            <td>
              <b>Note…</b>
            </td>
            <td>
              Name this step in your own words. What you type is used verbatim, so it is the fastest
              way to fix a step that would otherwise read badly.
            </td>
          </tr>
        </tbody>
      </table>
      <p className="note">
        None of these is required — the tool works with zero marks. They raise quality; they are
        never the price of admission.
      </p>

      <h2>Getting a better result</h2>

      <h3>Write a specific objective, or none at all</h3>
      <table className="compare">
        <thead>
          <tr>
            <th>Write this</th>
            <th>Not this</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Check that an order over €500 requires manager approval</td>
            <td>Test the checkout page</td>
          </tr>
          <tr>
            <td>Check that removing the last item empties the cart</td>
            <td>Cart stuff</td>
          </tr>
          <tr>
            <td>Check that an expired card is rejected at payment</td>
            <td>Payment flow</td>
          </tr>
        </tbody>
      </table>
      <p className="note">
        <b>A vague objective is worse than none at all</b>, and that is the opposite of what most
        people expect. The same recording, run with <i>“check if hamper sizes change correctly”</i>,
        produced three checks about sizes changing and never noticed the tester had hit the ceiling.
        Run with <i>nothing at all</i>, it found the real ending on its own. If you cannot say in
        one line what you are checking, leave it blank and record carefully instead.
      </p>

      <h3>The other four things that help</h3>
      <ul>
        <li>
          <b>One objective per recording.</b> Two things you were checking makes one document that
          is vague about both.
        </li>
        <li>
          <b>Work at your normal speed, one intent at a time.</b> Fill a form, then submit it, then
          look at the result. The tool reads a pause as “that was one thing”, so a session done in
          three seconds is harder to turn into readable steps than the same session in fifteen.
        </li>
        <li>
          <b>End on the thing you came to check</b>, and give it a moment. A verdict lives on the
          last thing that happened.
        </li>
        <li>
          <b>Say the number out loud.</b> “This should drop the list from twenty-four to nine” is
          worth more than any amount of clicking.
        </li>
      </ul>

      <h3>Leave Redaction alone unless you have a reason</h3>
      <p>
        Under the <span className="ui">⚙</span> in the popup. <b>Anything sensitive</b> is the
        default and the right answer almost always: passwords, card numbers, emails and phone
        numbers are replaced in the browser before anything is saved. Lower it only when the tool is
        hiding values your test actually needs — an order reference that happens to look like a card
        number, say.
      </p>
      <p className="note">
        <b>Everything you say out loud is written down.</b> Do not read a password aloud.{' '}
        <span className="ui">Mute</span> in the popup silences the microphone mid-recording without
        ending the recording.
      </p>

      <h2>Reading the draft</h2>
      <ul>
        <li>
          <b>Every expected result carries a badge</b> saying where it came from — whether you
          confirmed it, said it out loud, or the tool inferred it. An inferred verdict is the one to
          read twice.
        </li>
        <li>
          <b>Under each expected result is the exact text</b> the tool found on the page. If that
          text does not look like proof of the sentence above it, the sentence is wrong — say so.
        </li>
        <li>
          <b>A red dot beside a step</b> means a QA lead would send it back. Open the step: the
          reason and the suggested fix are written out under the expected result.
        </li>
        <li>
          <b>A step with no verdict says why</b>, in plain language. That is the tool refusing to
          claim something it could not prove, and it is working as intended.
        </li>
        <li>
          <b>What this session did not cover</b> is a suggestion about what to record next. Nothing
          checked it and it is not part of the test case.
        </li>
      </ul>

      <h3>What to actually do on that screen</h3>
      <p>
        Reword a step or a verdict, delete a step, merge two, approve. Fix wording that would
        confuse the next person; do not fix wording you merely would have phrased differently. Press{' '}
        <kbd>?</kbd> for the keyboard shortcuts, or <kbd>⌘</kbd>
        <kbd>K</kbd> to jump anywhere.
      </p>
      <p>
        You cannot edit the evidence under a claim, on purpose: a sentence and the proof beneath it
        have to stay honest about each other. If a verdict is wrong, delete it or reword the
        sentence — the proof stays what it was.
      </p>

      <h2>If something goes wrong</h2>
      <table className="compare">
        <tbody>
          <tr>
            <td>The recording came out empty</td>
            <td>
              The recorder only attaches to pages loaded after you pressed Start. Reload the page
              and record again.
            </td>
          </tr>
          <tr>
            <td>A step describes an icon instead of a button</td>
            <td>
              That control has no label the browser can read — a real accessibility problem, and
              worth reporting. Use <b>Note…</b> to name the step yourself.
            </td>
          </tr>
          <tr>
            <td>Nothing you said was picked up</td>
            <td>
              The popup shows a level meter while you talk. No movement means the microphone
              permission was refused or the wrong input is selected.
            </td>
          </tr>
          <tr>
            <td>“Nothing is listening”</td>
            <td>
              The review server is not running. Whoever set this up needs to start it; nothing you
              recorded is lost — save the file from the send page instead.
            </td>
          </tr>
        </tbody>
      </table>

      <h2>What the tool will not do</h2>
      <ul>
        <li>
          <b>Claim something it did not see.</b> Every verdict quotes text that actually came back
          off the page during your session, and it is checked again afterwards. A sentence that
          cannot point at its proof is refused, and the refusal tells you why.
        </li>
        <li>
          <b>Save a secret.</b> Redaction happens in the browser, before anything is written down.
          The one exception is what you say out loud, which cannot be hidden before it is
          understood — it stays on this machine.
        </li>
        <li>
          <b>Recognise a secret it never saw you type.</b> A value the application <i>displays</i>{' '}
          and you never entered looks exactly like ordinary page text. If your application shows
          one, it has to be named in the project's settings — ask whoever set this up.
        </li>
      </ul>
    </div>
  );
}

/**
 * The two moments the tool is waiting for you.
 *
 * The only thing about the process a user has to know. It replaced a drawing of
 * which stages run a model, which is a fact about the architecture: true, worth
 * documenting, and of no use whatsoever to somebody deciding what to do next.
 */
function Journey() {
  const steps: [string, string, 'you' | 'auto'][] = [
    ['record', 'use the app', 'you'],
    ['stop', 'the tool takes over', 'auto'],
    ['confirm', 'was that right?', 'you'],
    ['draft', 'a couple of minutes', 'auto'],
    ['review', 'fix the wording', 'you'],
    ['export', 'Gherkin, Excel, Jira', 'auto'],
  ];

  return (
    <figure className="pipeline">
      <svg viewBox="0 0 760 92" role="img" aria-label="What happens, and where you are needed">
        <title>Recording to test case, and the two moments that need you</title>
        {steps.map(([name, what, kind], i) => {
          const x = 12 + i * 126;
          return (
            <g key={name} transform={`translate(${x} 0)`}>
              <rect x="0" y="18" width="112" height="40" rx="6" className={`stage stage-${kind}`} />
              <text x="56" y="38" textAnchor="middle" className="stage-name">
                {name}
              </text>
              <text x="56" y="51" textAnchor="middle" className="stage-kind">
                {kind === 'you' ? 'you' : 'the tool'}
              </text>
              <text x="56" y="76" textAnchor="middle" className="stage-what">
                {what}
              </text>
              {i < steps.length - 1 && (
                <path d="M116 38 L124 38" className="stage-arrow" markerEnd="url(#tip)" />
              )}
            </g>
          );
        })}
        <defs>
          <marker id="tip" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0 0 L6 3 L0 6 z" className="stage-arrow-tip" />
          </marker>
        </defs>
      </svg>
      <figcaption>
        Three of the six are yours, and they are short. <b>Confirm</b> is the one that decides
        whether the test case can fail on a broken build — it is the only place the tool learns what{' '}
        <i>should</i> have happened.
      </figcaption>
    </figure>
  );
}
