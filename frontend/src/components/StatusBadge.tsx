interface StatusBadgeProps {
  value: string;
  subtle?: boolean;
}

export function StatusBadge({ value, subtle = false }: StatusBadgeProps) {
  const normalized = value.toUpperCase().replaceAll(" ", "_");
  return (
    <span className={`status-badge status-${normalized.toLowerCase()} ${subtle ? "status-subtle" : ""}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
