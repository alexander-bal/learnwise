import { useEffect, useRef, useState } from "react";
import {
  fetchReview,
  fetchReviews,
  isOpenReview,
  startReview,
  type JudgedOutput,
  type Review,
  type ReviewDetail,
  type ReviewPrompt,
  type StartReviewOutcome,
} from "./api";
import { CallsTable } from "./CallsTable";
import { Link, navigate } from "./router";
import { Badge, Loaded, Mono, Pager, Time } from "./ui";
import { useLoad } from "./useLoad";

const LIMIT = 50;
const REFRESH_MS = 2000;

/** Call `reload` every couple of seconds while `active`. */
function useRefreshWhile(active: boolean, reload: () => void) {
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(reload, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [active, reload]);
}

const reviewLink = (id: string) => `/reviews?id=${encodeURIComponent(id)}`;

export function ReviewsPage({ selected }: { selected: string | null }) {
  const [offset, setOffset] = useState(0);
  const { state, reload } = useLoad((signal) => fetchReviews(offset, LIMIT, signal), [offset], "reviews");
  const anyOpen = state.kind === "loaded" && state.data.items.some(isOpenReview);
  useRefreshWhile(anyOpen, reload);

  return (
    <section aria-labelledby="reviews-heading">
      <div className="heading-row">
        <h1 id="reviews-heading">Reviews</h1>
        <button type="button" onClick={reload}>
          Refresh
        </button>
      </div>
      <StartReview onStarted={reload} />
      {selected && <ReviewDetailPanel reviewId={selected} onChange={reload} />}
      <h2>All reviews</h2>
      <Loaded state={state} what="reviews" onRetry={reload}>
        {(page) =>
          page.items.length === 0 ? (
            <p className="muted">
              No reviews yet. Process a few messages on the <Link to="/">Process</Link> page, then start one.
            </p>
          ) : (
            <>
              <ReviewsTable reviews={page.items} selected={selected} />
              <Pager offset={offset} limit={LIMIT} total={page.total} onChange={setOffset} />
            </>
          )
        }
      </Loaded>
    </section>
  );
}

function StartReview({ onStarted }: { onStarted: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<StartReviewOutcome | null>(null);

  async function start() {
    setBusy(true);
    setResult(null);
    const outcome = await startReview();
    setBusy(false);
    setResult(outcome);
    if (outcome.kind === "started") {
      onStarted();
      navigate(reviewLink(outcome.reviewId));
    }
  }

  return (
    <div className="card">
      <p>
        A review judges the active prompt's most recent samples, proposes a new prompt from the errors, re-runs the
        samples under it, and promotes it only if it scores higher. The worker runs it in the background.
      </p>
      <button type="button" className="primary" onClick={start} disabled={busy}>
        {busy ? "Starting…" : "Start review"}
      </button>
      <div aria-live="polite">
        {result?.kind === "in_progress" && (
          <p className="error" role="alert">
            A review is already open: <Link to={reviewLink(result.reviewId)}>open it</Link>. Start another once it
            has ended.
          </p>
        )}
        {result?.kind === "error" && (
          <p className="error" role="alert">
            Could not start a review. {result.message}
          </p>
        )}
      </div>
    </div>
  );
}

function Outcome({ review }: { review: Pick<Review, "status" | "outcome"> }) {
  return (
    <span className="badges">
      <Badge value={review.status} />
      {review.outcome && <Badge value={review.outcome} />}
    </span>
  );
}

function Score({ review }: { review: Pick<Review, "base_score" | "candidate_score"> }) {
  if (review.base_score === null) return <span className="muted">-</span>;
  return (
    <span className="num">
      {review.base_score}
      {review.candidate_score !== null && <> → {review.candidate_score}</>}
    </span>
  );
}

function ReviewsTable({ reviews, selected }: { reviews: Review[]; selected: string | null }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Created</th>
            <th scope="col">Review</th>
            <th scope="col">Status</th>
            <th scope="col">Prompt</th>
            <th scope="col">Samples</th>
            <th scope="col">Score base → candidate</th>
            <th scope="col">Attempts</th>
            <th scope="col">Last error</th>
            <th scope="col">Next attempt</th>
          </tr>
        </thead>
        <tbody>
          {reviews.map((r) => (
            <tr key={r.id} className={r.id === selected ? "is-active" : undefined}>
              <td>
                <Time value={r.created_at} />
              </td>
              <td>
                <Link to={reviewLink(r.id)}>
                  <Mono value={r.id} short />
                </Link>
              </td>
              <td>
                <Outcome review={r} />
              </td>
              <td className="num">
                v{r.base_prompt_id}
                {r.candidate_prompt_id !== null && <> → v{r.candidate_prompt_id}</>}
              </td>
              <td className="num">{r.samples}</td>
              <td>
                <Score review={r} />
              </td>
              <td className="num">{r.attempts}</td>
              <td>{r.error_code ? <code title={r.error_message ?? undefined}>{r.error_code}</code> : <span className="muted">-</span>}</td>
              <td>{r.status === "pending" ? <Time value={r.next_attempt_at} /> : <span className="muted">-</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewDetailPanel({ reviewId, onChange }: { reviewId: string; onChange: () => void }) {
  const { state, reload } = useLoad((signal) => fetchReview(reviewId, signal), [reviewId], "the review");
  const open = state.kind === "loaded" && isOpenReview(state.data);
  useRefreshWhile(open, reload);
  // When the review ends, the list's last refresh may predate it: refresh it once more.
  const wasOpen = useRef(false);
  useEffect(() => {
    if (wasOpen.current && !open) onChange();
    wasOpen.current = open;
  }, [open, onChange]);

  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.scrollIntoView({ block: "start" });
    heading.current?.focus();
  }, [reviewId]);

  return (
    <section className="card detail" aria-labelledby="review-detail-heading">
      <div className="heading-row">
        <h2 id="review-detail-heading" ref={heading} tabIndex={-1}>
          Review <Mono value={reviewId} />
        </h2>
        <button type="button" onClick={() => navigate("/reviews")}>
          Close
        </button>
      </div>
      <Loaded state={state} what="the review" onRetry={reload}>
        {(review) => <ReviewBody review={review} />}
      </Loaded>
    </section>
  );
}

function ReviewBody({ review }: { review: ReviewDetail }) {
  return (
    <>
      <dl className="facts">
        <dt>Status</dt>
        <dd>
          <Outcome review={review} />
          {isOpenReview(review) && <span className="muted"> refreshing every 2 s</span>}
        </dd>
        <dt>Score</dt>
        <dd>
          <Score review={review} />
          {review.left_out > 0 && <span className="muted"> ({review.left_out} left out as unjudgeable)</span>}
        </dd>
        <dt>Attempts</dt>
        <dd className="num">{review.attempts}</dd>
        {review.error_code && (
          <>
            <dt>Last error</dt>
            <dd>
              <code>{review.error_code}</code> <span className="muted">{review.error_message}</span>
            </dd>
          </>
        )}
        {review.status === "pending" && review.next_attempt_at && (
          <>
            <dt>Next attempt</dt>
            <dd>
              <Time value={review.next_attempt_at} />
            </dd>
          </>
        )}
        <dt>Created</dt>
        <dd>
          <Time value={review.created_at} />
        </dd>
        <dt>Started</dt>
        <dd>
          <Time value={review.started_at} />
        </dd>
        <dt>Ended</dt>
        <dd>
          <Time value={review.completed_at} />
        </dd>
        <dt>Expires</dt>
        <dd>
          <Time value={review.expires_at} />
        </dd>
        <dt>Models</dt>
        <dd>
          {review.provider} / processing <code>{review.processing_model}</code>, judge <code>{review.judge_model}</code>
        </dd>
        <dt>Request</dt>
        <dd>
          <Mono value={review.request_id} />
        </dd>
      </dl>

      <h3>Prompts</h3>
      <div className="prompt-pair">
        <PromptCard title="Base" prompt={review.base_prompt} />
        <PromptCard
          title="Candidate"
          prompt={review.candidate_prompt}
          empty={candidateNote(review)}
        />
      </div>

      <h3>Samples</h3>
      {review.judgments.length === 0 ? (
        <p className="muted">{review.status === "completed" ? "No samples were selected." : "Not selected yet."}</p>
      ) : (
        <JudgmentsTable review={review} />
      )}

      <h3>Model calls</h3>
      {review.calls.length === 0 ? (
        <p className="muted">No model calls yet.</p>
      ) : (
        <CallsTable calls={review.calls} showRequest={false} />
      )}
    </>
  );
}

function candidateNote(review: ReviewDetail): string {
  if (review.outcome === "no_changes") return "None: no base output was in error.";
  if (review.outcome === "no_proposal") return "None: the proposal was invalid or equal to the base prompt.";
  if (review.outcome === "insufficient_samples") return "None: there were no samples to review.";
  if (review.status === "failed") return "None: the review failed before proposing one.";
  return "Not proposed yet.";
}

function PromptCard({ title, prompt, empty }: { title: string; prompt: ReviewPrompt | null; empty?: string }) {
  return (
    <div className="prompt-card">
      <h4>
        {title}
        {prompt && (
          <>
            {" "}
            v{prompt.id} <Badge value={prompt.status} />
          </>
        )}
      </h4>
      {prompt ? (
        <>
          {prompt.parent_id !== null && <p className="muted">Reason: {prompt.change_reason}</p>}
          <pre className="prompt-text">{prompt.content}</pre>
        </>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </div>
  );
}

function Judgment({ side }: { side: JudgedOutput | null }) {
  if (side === null) return <span className="muted">-</span>;
  return (
    <div className="judgment">
      {side.output ? (
        <span>
          <Badge value={side.output.intent} /> <span className="muted">{side.output.urgency}</span>
        </span>
      ) : (
        <span className="badge badge-error">no valid output</span>
      )}
      <div className="muted small">
        {!side.judged ? (
          side.output ? "not judged yet" : "not judged"
        ) : side.unjudgeable ? (
          <span title={side.explanation ?? undefined}>unjudgeable</span>
        ) : (
          <span title={side.explanation ?? undefined}>
            judge: {side.expected!.intent} / {side.expected!.urgency} · {side.points} pt{side.points === 1 ? "" : "s"}
            {side.in_error && <strong className="in-error"> in error</strong>}
          </span>
        )}
      </div>
    </div>
  );
}

function JudgmentsTable({ review }: { review: ReviewDetail }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Message</th>
            <th scope="col">Base v{review.base_prompt_id}</th>
            <th scope="col">Candidate{review.candidate_prompt_id !== null && ` v${review.candidate_prompt_id}`}</th>
            <th scope="col">Scored</th>
          </tr>
        </thead>
        <tbody>
          {review.judgments.map((j) => (
            <tr key={j.sample_id}>
              <td>
                <div className="content" title={j.message}>
                  {j.message}
                </div>
              </td>
              <td>
                <Judgment side={j.base} />
              </td>
              <td>
                <Judgment side={j.candidate} />
              </td>
              <td>{j.left_out ? <span className="muted">left out</span> : "yes"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
