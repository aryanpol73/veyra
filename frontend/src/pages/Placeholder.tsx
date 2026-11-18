import { Empty } from "../components/ui";

export default function Placeholder({ title, phase, what }: { title: string; phase: number; what: string }) {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{title}</h1>
      <Empty>
        <div className="font-medium text-zinc-700 dark:text-zinc-300">Not built yet (Phase {phase})</div>
        <div className="mt-1">{what}</div>
      </Empty>
    </div>
  );
}
