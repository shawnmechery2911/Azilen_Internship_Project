export function IssueList({
  issues,
}: {
  issues: { field: string; message: string; group?: string }[];
}) {
  return (
    <ul className="issue-list">
      {issues.map((issue, index) => (
        <li className="issue-row" key={`${issue.field}-${index}`}>
          <span className={`issue-tag tag-${(issue.group ?? "Mapping").toLowerCase()}`}>
            {issue.group ?? "Mapping"}
          </span>
          <code>{issue.field}</code>
          <span>{issue.message}</span>
        </li>
      ))}
    </ul>
  );
}
