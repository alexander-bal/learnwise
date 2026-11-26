import type { LlmCall } from "./api";
import { Link } from "./router";
import { Badge, Mono, Time } from "./ui";

export function CallsTable({ calls, showRequest = true }: { calls: LlmCall[]; showRequest?: boolean }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Started</th>
            {showRequest && <th scope="col">Request</th>}
            <th scope="col">Operation</th>
            <th scope="col">Model</th>
            <th scope="col">Attempt</th>
            <th scope="col">Status</th>
            <th scope="col">Tokens in / out</th>
            <th scope="col">Duration</th>
            <th scope="col">Error</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr key={c.id}>
              <td>
                <Time value={c.created_at} />
              </td>
              {showRequest && (
                <td>
                  <Link to={`/requests?id=${encodeURIComponent(c.request_id)}`}>
                    <Mono value={c.request_id} short />
                  </Link>
                </td>
              )}
              <td>{c.operation}</td>
              <td>
                {c.provider} / <code>{c.model}</code>
              </td>
              <td className="num">{c.attempt}</td>
              <td>
                <Badge value={c.status} />
              </td>
              <td className="num">
                {c.input_tokens ?? "-"} / {c.output_tokens ?? "-"}
              </td>
              <td className="num">{c.duration_ms === null ? "-" : `${c.duration_ms} ms`}</td>
              <td>
                {c.error_code ? (
                  <span title={c.error_message ?? undefined}>
                    <code>{c.error_code}</code>
                    {c.error_message && <span className="muted"> {c.error_message}</span>}
                  </span>
                ) : (
                  <span className="muted">-</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
