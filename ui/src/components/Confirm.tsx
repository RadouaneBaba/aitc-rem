import { useCallback, useEffect, useState } from 'react';
import {
  api,
  type Expectation,
  type ExpectationAnswer,
  type ExpectationSet,
  type ExpectationSource,
} from '../api';

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
 * the run that already happened stands, and its scenarios carry @needs-review.
 * A run must never wait on a screen somebody might not open.
 */

type Answers = Record<string, ExpectationAnswer>;

const RETRY_MS = 1500;

export function Confirm({ recordingId, onDone }: { recordingId: string; onDone: () => void }) {
  const [set, setSet] = useState<ExpectationSet | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

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
      await api.answerExpectations(recordingId, list);
      setSent(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [answers, recordingId]);

  if (error) return <Shell onDone={onDone}><p className="bad">{error}</p></Shell>;

  if (sent) {
    return (
      <Shell onDone={onDone}>
        <p className="ok">
          Thank you — that is the part nothing else could work out. A new draft is being
          written with your answers.
        </p>
        <button className="primary" onClick={onDone}>
          Open the drafts
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
        <button className="primary" onClick={onDone}>
          Open the drafts
        </button>
      </Shell>
    );
  }

  const answered = Object.keys(answers).length;

  return (
    <Shell onDone={onDone}>
      <p className="muted confirm-lead">
        Here is what we think should have happened. You are the only one who knows — the
        recording can only show what the application <em>did</em>. Answer what you can and skip
        the rest.
      </p>

      <ol className="confirm-list">
        {set.expectations.map((expectation) => (
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
        <button className="ghost" onClick={onDone}>
          Skip — a draft was written without them
        </button>
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

  return (
    <li className={`confirm-card${chosen ? ` answered ${chosen}` : ''}`}>
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
            {expectation.observed && (
              <>
                <dt>Actually</dt>
                <dd>{expectation.observed}</dd>
              </>
            )}
          </dl>

          <div className="confirm-buttons">
            <button
              className={chosen === 'confirmed' ? 'primary' : 'secondary'}
              onClick={() => onAnswer(expectation.id, 'confirmed')}
            >
              Right
            </button>
            {/* The button that finds bugs. A rejected expectation says the
                application did the wrong thing, which is the one finding the
                recording alone can never produce. */}
            <button
              className={chosen === 'rejected' ? 'primary' : 'secondary'}
              onClick={() => onAnswer(expectation.id, 'rejected')}
            >
              Not right
            </button>
            <button className="ghost" onClick={onEdit}>
              Edit
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

function Shell({ children, onDone }: { children: React.ReactNode; onDone: () => void }) {
  return (
    <div className="confirm">
      <header className="confirm-head">
        <h1>Was that right?</h1>
        <button className="ghost" onClick={onDone}>
          Drafts
        </button>
      </header>
      {children}
    </div>
  );
}
