/**
 * How to USE this, as a page you can reach.
 *
 * It existed as `docs/HOWTO.md` and `docs/RECORDING.md` -- two good documents in
 * a repository, which is the wrong place for at least one of their two
 * audiences. A tester who never opens a terminal has no route to a markdown
 * file, and "read the README" is not a route.
 *
 * **It is a guide to DOING the task, and deliberately not an explanation of the
 * machine.** It was both for a day, and being both is what made it neither: half
 * the page was CLI invocations, `project.yaml` keys and a drawing of which
 * stages run a model -- none of which is reachable, or actionable, or even
 * visible to the person this page is for. Everything a reader can only act on
 * from a terminal now lives in `docs/HOWTO.md`, which is the operator's
 * document; everything about why the pipeline is shaped as it is lives in
 * `docs/DESIGN_NOTES.md`. What is left here is what somebody with the extension
 * and this browser tab can actually do.
 *
 * **Written from what actually works, not from the spec.** That is a rule with
 * a reason: parts of this codebase have never run against a real recording, and
 * a how-to written from the design would document features that do not exist.
 * Everything named below is something that has run, and every button named
 * below is a button that exists.
 *
 * The one diagram is inline SVG rather than a screenshot. Screenshots of a UI
 * that is still moving go stale silently and there is nothing that notices. And
 * it draws the two moments where the tool is WAITING FOR YOU, which is the one
 * thing about the process a user has to know -- not which stages use a model.
 */

export function Help({ onBack }: { onBack: () => void }) {
  return (
    <div className="help">
      <header>
        <h1>How to use this</h1>
        <div className="spacer" />
        <button onClick={onBack}>Back to the review</button>
      </header>

      <p className="muted">
        You record yourself using the application and answer two short screens.
        The tool writes the test cases. No terminal, at any point.
      </p>

      <Journey />

      <section>
        <h2>Before you press record</h2>

        <h3>Say what you are checking</h3>
        <p>
          The popup asks <em>“What are you checking?”</em> before it will start.
          One line. It is the one thing the tool can never work out for itself:
          it can see that you clicked <b>Place order</b>, but not that you were
          checking the €500 approval rule rather than the discount, and a
          checkout page changes twenty things at once.
        </p>
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
          <b>A vague objective is worse than none at all</b>, and that is the
          opposite of what most people expect. The same recording, run with
          <i> “check if hamper sizes change correctly”</i>, produced three checks
          about sizes changing and never noticed the tester had hit the ceiling.
          Run with <i>nothing at all</i>, it found the real ending on its own. If
          you cannot say in one line what you are checking, leave it blank and
          record carefully instead.
        </p>

        <h3>Turn on “Talk while I record”</h3>
        <p>
          It is the cheapest way to give the tool something to check against, and
          it is off until you turn it on. Your voice is transcribed on this
          machine and never uploaded.
        </p>
        <p className="note">
          <b>Everything you say is written down.</b> Do not read a password
          aloud. <b>Mute</b> in the popup silences the microphone mid-recording
          without ending the recording.
        </p>

        <h3>Leave Redaction alone unless you have a reason</h3>
        <p>
          <b>Everything that looks sensitive</b> is the default and the right
          answer almost always: passwords, card numbers, emails and phone numbers
          are replaced
          in the browser before anything is saved. Lower it only when the tool is
          hiding values your test actually needs — an order reference that
          happens to look like a card number, say — and read what the popup says
          when you do.
        </p>
      </section>

      <section>
        <h2>While you record</h2>

        <h3>Work at your normal speed, one intent at a time</h3>
        <p>
          Slightly slower is better than faster. Fill a form, then submit it,
          then look at the result — the tool reads a pause as “that was one
          thing”, so a session done in three seconds is harder to turn into
          readable steps than the same session done in fifteen.
        </p>

        <h3>Mark what you are verifying</h3>
        <p>
          The most useful button in the popup. Press it when you are looking at
          the thing you came to check, and the tool knows that <i>this</i> screen
          is the point of the session rather than one more page you passed
          through.
        </p>

        <h3>The other four</h3>
        <table className="compare">
          <tbody>
            <tr>
              <td>
                <b>Checkpoint</b>
              </td>
              <td>A moment worth coming back to. No other effect.</td>
            </tr>
            <tr>
              <td>
                <b>New scenario</b>
              </td>
              <td>
                A second test case starts here. This is not a suggestion —
                wherever you press it the scenario is cut, and nothing overrules
                you.
              </td>
            </tr>
            <tr>
              <td>
                <b>Mark a bug</b>
              </td>
              <td>
                Something just went wrong. The test case is written to expect the
                CORRECT behaviour, so it fails on this build — which is the
                point.
              </td>
            </tr>
            <tr>
              <td>
                <b>Note…</b>
              </td>
              <td>
                Name this step in your own words. What you type is used verbatim,
                so it is the fastest way to fix a step that would otherwise read
                badly.
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>After you press Stop</h2>

        <h3>The confirmation screen — the most valuable minute you will spend</h3>
        <p>
          The tool guesses what <em>should</em> have happened for each thing you
          did and shows you the guesses over screenshots. Tick, correct the
          wording, or press <b>Not right</b>.
        </p>
        <p>
          <b>Not right</b> is the most valuable button in the product. The
          recording can only tell the tool what the application <i>did</i>; it is
          the only way the tool can learn that what it recorded was a bug.
        </p>
        <p className="note">
          You can skip it, and a draft is written from the guesses either way.
          But a test case built on an unchecked guess can only ever restate what
          the application already does — it will pass on a broken build. If you
          answer nothing else, answer the guesses that look wrong.
        </p>

        <h3>Then the draft</h3>
        <p>
          A couple of minutes. The tool is going back through the recording and
          proving each verdict against what was actually on the page, which is
          the slow part and the part worth waiting for.
        </p>

        <h3>Reading it</h3>
        <ul>
          <li>
            <b>Every expected result carries a badge</b> saying where it came
            from — whether you confirmed it, said it out loud, or the tool
            inferred it. An inferred verdict is the one to read twice.
          </li>
          <li>
            <b>Under each expected result is the exact text</b> the tool found on
            the page. If that text does not look like proof of the sentence above
            it, the sentence is wrong — say so.
          </li>
          <li>
            <b>A step with no verdict says why</b>, in plain language. That is
            the tool refusing to claim something it could not prove, and it is
            working as intended.
          </li>
          <li>
            <b>UNVERIFIED</b> is a suggestion about what else is worth testing.
            It is not part of the test case and nothing checked it.
          </li>
        </ul>

        <h3>What to actually do on this screen</h3>
        <p>
          Reword a step or a verdict, delete a step, merge two, approve. Fix
          wording that would confuse the next person; do not fix wording you
          merely would have phrased differently.
        </p>
        <p>
          You cannot edit the evidence under a claim, on purpose: a sentence and
          the proof beneath it have to stay honest about each other. If a verdict
          is wrong, delete it or reword the sentence — the proof stays what it
          was.
        </p>
        <p className="note">
          Every change you make is recorded. That record is the only thing that
          tells us which kinds of step the tool gets wrong, so editing the draft
          is not just fixing today's output.
        </p>
      </section>

      <section>
        <h2>Getting a better result</h2>
        <ul>
          <li>
            <b>One objective per recording.</b> Two things you were checking
            makes one document that is vague about both.
          </li>
          <li>
            <b>End on the thing you came to check</b>, and give it a moment. A
            verdict lives on the last thing that happened.
          </li>
          <li>
            <b>Say the number out loud.</b> “This should drop the list from
            twenty-four to nine” is worth more than any amount of clicking.
          </li>
          <li>
            <b>Record the failure when you find one.</b> Press <b>Mark a bug</b>{' '}
            and keep going — a recording of something broken is more valuable
            than a recording of something working.
          </li>
        </ul>
      </section>

      <section>
        <h2>If something goes wrong</h2>
        <table className="compare">
          <tbody>
            <tr>
              <td>The recording came out empty</td>
              <td>
                The extension only attaches to pages loaded after you pressed
                Start. Reload the page and record again.
              </td>
            </tr>
            <tr>
              <td>A step describes an icon instead of a button</td>
              <td>
                That control has no label the browser can read — a real
                accessibility problem, and worth reporting. Use <b>Note…</b> to
                name the step yourself.
              </td>
            </tr>
            <tr>
              <td>Nothing you said was picked up</td>
              <td>
                The popup shows a level meter while you talk. No movement means
                the microphone permission was refused or the wrong input is
                selected.
              </td>
            </tr>
            <tr>
              <td>“Could not reach the server”</td>
              <td>
                The review server is not running. Whoever set this up needs to
                start it; nothing you recorded is lost.
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>What the tool will not do</h2>
        <ul>
          <li>
            <b>Claim something it did not see.</b> Every verdict quotes text that
            actually came back off the page during your session, and it is
            checked again afterwards. A sentence that cannot point at its proof
            is refused, and the refusal tells you why.
          </li>
          <li>
            <b>Save a secret.</b> Redaction happens in the browser, before
            anything is written down. The one exception is what you say out loud,
            which cannot be hidden before it is understood — it stays on this
            machine.
          </li>
          <li>
            <b>Recognise a secret it never saw you type.</b> A value the
            application <i>displays</i> and you never entered looks exactly like
            ordinary page text. If your application shows one, it has to be named
            in the project's settings — ask whoever set this up.
          </li>
        </ul>
      </section>
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
        Three of the six are yours, and they are short. <b>Confirm</b> is the one
        that decides whether the test case can fail on a broken build — it is the
        only place the tool learns what <i>should</i> have happened.
      </figcaption>
    </figure>
  );
}
