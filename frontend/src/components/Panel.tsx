import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  icon: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, icon: Icon, action, children, className = "" }: PanelProps) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div className="panel-title"><Icon size={17} aria-hidden="true" /><h2>{title}</h2></div>
        {action}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
