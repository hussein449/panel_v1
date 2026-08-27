import Link from "next/link";

export const metadata = { title: "No such page" };

export default function NotFound() {
  return (
    <div className="shell-page">
      <div className="shell-card">
        <h2>No such page</h2>
        <p>
          There is nothing at this address. The banner above still says what this
          deployment is, because it is drawn by the layout and this page is inside it.
        </p>
        <p>
          <Link href="/">Start again</Link>
        </p>
      </div>
    </div>
  );
}
