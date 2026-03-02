import Link from "next/link";

export default function Navbar() {
  return (
    <nav className="border-b border-neutral-200 bg-white px-6 py-3 dark:border-neutral-800 dark:bg-neutral-950">
      <Link href="/" className="text-lg font-semibold text-foreground">
        GraphMentor
      </Link>
    </nav>
  );
}
