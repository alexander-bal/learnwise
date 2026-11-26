import { useState } from "react";
import { fetchSamples } from "./api";
import { Link } from "./router";
import { Badge, Loaded, Mono, Pager, Time } from "./ui";
import { useLoad } from "./useLoad";

const LIMIT = 50;

export function SamplesPage() {
  const [offset, setOffset] = useState(0);
  const { state, reload } = useLoad((signal) => fetchSamples(offset, LIMIT, signal), [offset], "samples");

  return (
    <section aria-labelledby="samples-heading">
      <div className="heading-row">
        <h1 id="samples-heading">Samples</h1>
        <button type="button" onClick={reload}>
          Refresh
        </button>
      </div>
      <Loaded state={state} what="samples" onRetry={reload}>
        {(page) =>
          page.items.length === 0 ? (
            <p className="muted">
              No samples yet. A message processed on the <Link to="/">Process</Link> page is stored here.
            </p>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Created</th>
                      <th scope="col">Message</th>
                      <th scope="col">Intent</th>
                      <th scope="col">Urgency</th>
                      <th scope="col">Prompt</th>
                      <th scope="col">Model</th>
                      <th scope="col">Request</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((s) => (
                      <tr key={s.id}>
                        <td>
                          <Time value={s.created_at} />
                        </td>
                        <td>
                          <div className="content" title={s.input}>
                            {s.input}
                          </div>
                        </td>
                        <td>
                          <Badge value={s.output.intent} />
                        </td>
                        <td>
                          <span className={`badge badge-urgency-${s.output.urgency}`}>{s.output.urgency}</span>
                        </td>
                        <td className="num">v{s.prompt_version_id}</td>
                        <td>
                          {s.provider} / <code>{s.model}</code>
                        </td>
                        <td>
                          <Link to={`/requests?id=${encodeURIComponent(s.request_id)}`}>
                            <Mono value={s.request_id} short />
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager offset={offset} limit={LIMIT} total={page.total} onChange={setOffset} />
            </>
          )
        }
      </Loaded>
    </section>
  );
}
