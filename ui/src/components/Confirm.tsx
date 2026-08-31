import { useCallback, useEffect, useState } from 'react';
import {
  api,
  type Expectation,
  type ExpectationAnswer,
  type ExpectationSet,
  type ExpectationSource,
} from '../api';
import { Wordmark } from './Wordmark';

/**
 * An observed line that carries no information, which is worse than none.
 *
 * Live on disk: *"Actually: the page re-rendered with new content."* Under a
 * confident question that is not context, it is an admission that the tool did
 * not work out what changed -- and it makes the guess above it look like a
 * guess. Suppressed rather than shown, so the question stands on its own.
 *
 * Deliberately narrow: anything naming a value, a number or a quoted string is
 * informative and survives. Only the generic "something happened" shapes go.
 */
const VAGUE = /^(the )?(page|content|view|list|screen|dom)\b[^"'0-9]*\b(re-?rendered|updated|changed|refreshed|reloaded)\b[^"'0-9]*$/i;

function informative(observed: string | undefined): observed is string {
  return Boolean(observed && !VAGUE.test(observed.trim()));
}

/**
 * The confirmation screen.
 *
 * There is no oracle. The recording says what the application DID, which cannot
 * tell you whether it was right, and the objective names a feature rather than
 * a behaviour -- the real ones on disk read "check if filters are working
 * correctly", and four of four such objectives produced a run the judge called
 * bad. Every claim the pipeline can license is therefore a restatement of
 * observed behaviour.
 *
 * This screen is where that stops being true, and the entire design rests on
 * one observation: **do not ask open questions.** A tester will not write a
 * sentence. They will read one and press a button. So the model guesses, and
 * this shows the guess over the screenshot at the one moment they still
 * remember what they were doing:
 *
 *     You filtered the list to in-stock products.
 *     [ screenshot ]
 *     Should have: the list drops from 24 products to 9
 *     Actually:    the count changed from 24 to 9
 *     [ Right ]  [ Not right ]  [ Edit ]
 *
 * "Not right" is the most valuable button here and the reason the third option
 * is not just "edit": it means the recording contains a BUG, and the author
 * writes a bug report instead of a passing step. Nothing else in the tool can
 * discover that.
 *
 * Skipping is legitimate and costs nothing: unanswered guesses stay `inferred`,
 * the scenarios that rest on them carry @needs-review, and the draft is written
 * either way. A run must never wait on a screen somebody might not open.
 *
 * What it does do is hold, briefly. Answers are an INPUT to authoring rather
 * than an edit to its output, so a recording answered after the fact has to be
 * authored again -- and that repeats the author (up to two rounds) and the
 * judge after each, to replace a draft nobody had read. So the run stops
 * between the guess and the author for `confirm_window_seconds`, and answering
 * inside that window costs one run instead of two. `holdingUntil` says whether
 * that is happening; when it is absent this screen behaves exactly as it always
 * did, because answering late must still count.
 */

type Answers = Record<string, ExpectationAnswer>;

const RETRY_MS = 1500;

/**
 * Outcomes first, then the rest, each keeping the order the session had.
 *
 * Every card used to be flat and equal, so a tester who answered three of them
 * never saw the sentence describing what they had actually come to check. Their
 * words: the objective says *check the bag shows the correct prices*, and what
 * came back was a card per step result.
 *
 * The fix is ordering rather than filtering. A waypoint is a real checkable
 * fact and the tester's answer to one is as binding as their answer to an
 * outcome -- what was missing was any sign of which one is the point. This is
 * also why the answer was never "ask one vague question instead": a card naming
 * no value is the card nobody can tick.
 *
 * A run whose expectations predate `rank` has none of them marked, and this
 * returns them untouched.
 */
function ordered(expectations: Expectation[]): Expectation[] {
  return [
    ...expectations.filter((e) => e.rank === 'outcome'),
    ...expectations.filter((e) => e.rank !== 'outcome'),
  ];
}

/**
 * Seconds until authoring starts on its own, or null if nothing is holding.
 *
 * Recomputed from the deadline every tick rather than decremented, so a tab
 * that was backgrounded -- which throttles timers to once a minute -- shows the
 * truth when it comes back rather than a count that fell behind by however long
 * it was hidden.
 */
function useHold(holdingUntil: string | null | undefined): number | null {
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!holdingUntil) {
      setLeft(null);
      return;
    }
    const deadline = new Date(holdingUntil).getTime();
    if (Number.isNaN(deadline)) {
      setLeft(null);
      return;
    }
    const tick = () => setLeft(Math.max(0, Math.round((deadline - Date.now()) / 1000)));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [holdingUntil]);

  return left;
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const ss = String(seconds % 60).padStart(2, '0');
  return m > 0 ? `${m}:${ss}` : `${seconds}s`;
}


export function Confirm({
  recordingId,
  onDone,
}: {
  recordingId: string;
  /** Called with the run the answers started, when there is one. Answering
   *  re-runs the recording IN PLACE, so the right place to land is the run
   *  being rewritten -- not the drafts list, which is where this used to go and
   *  which shows the draft that is about to be replaced. */
  onDone: (runId?: string) => void;
}) {
  const [set, setSet] = useState<ExpectationSet | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [startedRun, setStartedRun] = useState<string | null>(null);
  const [foldedIn, setFoldedIn] = useState(false);
  const holdLeft = useHold(set?.holdingUntil);

  // The guess runs as its own stage of a job that started when the tester
  // pressed Send, so arriving here first is normal rather than an error. Poll
  // rather than fail: this screen is often the first thing they open.
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const load = () => {
      api
        .expectations(recordingId)
        .then((next) => live && setSet(next))
        .catch(() => {
          if (live) timer = window.setTimeout(load, RETRY_MS);
        });
    };
    load();
    return () => {
      live = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [recordingId]);

  const answer = useCallback((id: string, source: ExpectationSource, expected?: string) => {
    setAnswers((current) => ({ ...current, [id]: { id, source, ...(expected ? { expected } : {}) } }));
    setEditing(null);
  }, []);

  const submit = useCallback(async () => {
    const list = Object.values(answers);
    if (!list.length) return;
    setBusy(true);
    try {
      const { job, foldedIn: folded } = await api.answerExpectations(recordingId, list);
      setStartedRun(job?.runId ?? null);
      setFoldedIn(Boolean(folded));
      setSent(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [answers, recordingId]);

  /**
   * Write the draft now, on the guesses.
   *
   * Best-effort by design: if the window has already closed there is nothing to
   * release, and the tester's intent -- I have nothing to add, get on with it --
   * is already satisfied. Failing here would tell somebody who did the right
   * thing that they did something wrong.
   */
  const skip = useCallback(async () => {
    await api.skipExpectations(recordingId).catch(() => undefined);
    onDone();
  }, [recordingId, onDone]);

  if (error) return <Shell onDone={onDone}><p className="bad">{error}</p></Shell>;

  if (sent) {
    return (
      <Shell onDone={onDone}>
        <p className="ok">
          Thank you — that is the part nothing else could work out.{' '}
          {foldedIn
            ? 'The draft is being written with your answers, first time.'
            : 'The draft is being rewritten with your answers.'}
        </p>
        <button className="primary" onClick={() => onDone(startedRun ?? undefined)}>
          {startedRun ? (foldedIn ? 'Watch it being written' : 'Watch it being rewritten') : 'Open the drafts'}
        </button>
      </Shell>
    );
  }

  if (!set) {
    return (
      <Shell onDone={onDone}>
        <p className="muted">Working out what should have happened…</p>
      </Shell>
    );
  }

  if (!set.expectations.length) {
    return (
      <Shell onDone={onDone}>
        <p className="muted">
          Nothing in this session looked like a check worth confirming. That usually means it
          was all navigation and setup.
        </p>
        <button className="primary" onClick={() => onDone()}>
          Open the drafts
        </button>
      </Shell>
    );
  }

  const answered = Object.keys(answers).length;

  return (
    <Shell onDone={onDone} progress={{ answered, total: set.expectations.length }}>
      <p className="muted confirm-lead">
        Here is what we think should have happened. You are the only one who knows — the
        recording can only show what the application <em>did</em>. Answer what you can and skip
        the rest.
      </p>

      {/* Why a countdown and not a spinner: the tester is deciding whether to
          answer eight cards, and the honest input to that decision is how long
          they have. Nothing is lost when it reaches zero -- answering late
          still counts, it just rewrites the draft instead of writing it -- so
          this says what it costs rather than threatening a deadline. */}
      {holdLeft !== null && (
        <p className={`confirm-hold${holdLeft > 0 ? '' : ' elapsed'}`}>
          {holdLeft > 0 ? (
            <>
              <b>Waiting for you.</b> The draft is written with your answers if you finish
              within <b>{clock(holdLeft)}</b> — after that it starts on its own, and answering
              rewrites it.
            </>
          ) : (
            <>
              <b>The draft has started.</b> Answering still counts — it will rewrite what is
              being written now.
            </>
          )}
        </p>
      )}

      <ol className="confirm-list">
        {ordered(set.expectations).map((expectation) => (
          <Card
            key={expectation.id}
            recordingId={recordingId}
            expectation={expectation}
            answer={answers[expectation.id]}
            editing={editing === expectation.id}
            onEdit={() => setEditing(expectation.id)}
            onCancelEdit={() => setEditing(null)}
            onAnswer={answer}
          />
        ))}
      </ol>

      <div className="confirm-actions">
        <button className="primary" disabled={!answered || busy} onClick={submit}>
          {answered ? `Use these ${answered} answer${answered === 1 ? '' : 's'}` : 'Answer one to continue'}
        </button>
        {/* Two different sentences, because two different things are true. While
            the run is holding, skipping STARTS the draft; once it has started,
            skipping is just walking away from one. The old label said the
            second in both cases, which was about to become a lie. */}
        {holdLeft !== null && holdLeft > 0 ? (
          <button className="ghost" onClick={skip}>
            Skip — write the draft now
          </button>
        ) : (
          <button className="ghost" onClick={() => onDone()}>
            Skip — a draft was written without them
          </button>
        )}
      </div>
    </Shell>
  );
}

function Card({
  recordingId,
  expectation,
  answer,
  editing,
  onEdit,
  onCancelEdit,
  onAnswer,
}: {
  recordingId: string;
  expectation: Expectation;
  answer?: ExpectationAnswer;
  editing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onAnswer: (id: string, source: ExpectationSource, expected?: string) => void;
}) {
  const [draft, setDraft] = useState(expectation.expected);
  const eventId = expectation.eventIds[expectation.eventIds.length - 1];
  const chosen = answer?.source;

  const outcome = expectation.rank === 'outcome';

  return (
    <li className={`confirm-card${outcome ? ' outcome' : ''}${chosen ? ` answered ${chosen}` : ''}`}>
      {/* Which card is the point. Sorting alone moves it to the top and says
          nothing about why it is there, and a tester with eight cards reads the
          first one as simply first. */}
      {outcome && <span className="rank-tag">what you came to check</span>}
      <h3>{expectation.action}</h3>

      {expectation.screenshot && (
        // The screenshot is the whole reason this screen works. Judging "was
        // that right" from a semantic tree is hard; from the picture of the
        // page it is immediate.
        <img
          className="confirm-shot"
          src={`/api/recordings/${recordingId}/screens/${eventId}`}
          alt={`the page at ${eventId}`}
          loading="lazy"
        />
      )}

      {editing ? (
        <div className="confirm-edit">
          <label htmlFor={`edit-${expectation.id}`}>What should have happened?</label>
          <textarea
            id={`edit-${expectation.id}`}
            rows={2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="muted">
            Name something that would be different if this were broken — “the list drops to 9
            products”, not “the filter works”.
          </p>
          <button className="primary" onClick={() => onAnswer(expectation.id, 'corrected', draft.trim())}>
            Save
          </button>
          <button className="ghost" onClick={onCancelEdit}>
            Cancel
          </button>
        </div>
      ) : (
        <>
          <dl className="confirm-pair">
            <dt>Should have</dt>
            <dd>{answer?.expected ?? expectation.expected}</dd>
            {informative(expectation.observed) && (
              <>
                <dt>Actually</dt>
                <dd>{expectation.observed}</dd>
              </>
            )}
          </dl>

          {/* The common answer carries the weight. All three used to be
              identical plain outlines, so the screen asked a question and then
              offered no opinion about which answer was ordinary. */}
          <div className="confirm-buttons">
            <button
              className={chosen === 'confirmed' ? 'primary' : ''}
              onClick={() => onAnswer(expectation.id, 'confirmed')}
            >
              Right
            </button>
            {/* The button that finds bugs. A rejected expectation says the
                application did the wrong thing, which is the one finding the
                recording alone can never produce. */}
            <button
              className={`no${chosen === 'rejected' ? ' on' : ''}`}
              onClick={() => onAnswer(expectation.id, 'rejected')}
            >
              Not right
            </button>
            <button className="ghost" onClick={onEdit}>
              Reword
            </button>
          </div>

          {chosen === 'rejected' && (
            <p className="muted confirm-flag">
              Recorded as a bug: the draft will say what you expected and what the application
              did instead.
            </p>
          )}
        </>
      )}
    </li>
  );
}

function Shell({
  children,
  onDone,
  progress,
}: {
  children: React.ReactNode;
  onDone: () => void;
  /** How many of how many. There was none, so three cards read as an unbounded
   *  scroll -- and this screen only works if somebody can see it ending. */
  progress?: { answered: number; total: number };
}) {
  return (
    <div className="confirm">
      <header className="confirm-head">
        <Wordmark small />
        <h1>Was that right?</h1>
        <div className="spacer" />
        {progress && progress.total > 0 && (
          <span className="confirm-progress">
            <span className="pips">
              {Array.from({ length: progress.total }, (_, i) => (
                <span key={i} className={`pip${i < progress.answered ? ' done' : ''}`} />
              ))}
            </span>
            {progress.answered} of {progress.total}
          </span>
        )}
        <button className="ghost" onClick={() => onDone()}>
          Drafts
        </button>
      </header>
      {children}
    </div>
  );
}
