import './globals.css';

export const metadata = {
  title: 'OpsHub – AI Operations',
  description: 'AI Operations Automation Hub',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
