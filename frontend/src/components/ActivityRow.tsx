import { MoreHorizontal } from "lucide-react";

export type Activity = {
  partner: string;
  payload: string;
  result: "Processed" | "Exception" | "Needs mapping";
  time: string;
  version: string;
  icon: string;
};

export function ActivityRow({ item }: { item: Activity }) {
  return (
    <tr>
      <td>
        <div className="table-partner">
          <span className="table-avatar">{item.icon}</span>
          <strong>{item.partner}</strong>
        </div>
      </td>
      <td>{item.payload}</td>
      <td>
        <span
          className={`result-pill ${
            item.result === "Processed"
              ? "result-good"
              : item.result === "Exception"
                ? "result-bad"
                : "result-pending"
          }`}
        >
          <span />
          {item.result}
        </span>
      </td>
      <td>
        <span className="version-tag">{item.version}</span>
      </td>
      <td className="muted-cell">{item.time}</td>
      <td>
        <button
          className="row-menu"
          aria-label={`More options for ${item.partner}`}
        >
          <MoreHorizontal size={16} />
        </button>
      </td>
    </tr>
  );
}
