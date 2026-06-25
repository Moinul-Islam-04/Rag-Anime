import "./globals.css";

export const metadata = {
  title: "Anime RAG Recommender",
  description: "Cited anime recommendations via retrieval-augmented generation",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
