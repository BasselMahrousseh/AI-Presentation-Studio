interface EandLightOverlayProps {
  className?: string;
}

export default function EandLightOverlay({ className = "" }: EandLightOverlayProps) {
  return (
    <div className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`} aria-hidden="true">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_70%_52%_at_8%_0%,rgba(230,0,0,0.15),transparent_74%),radial-gradient(ellipse_52%_48%_at_92%_18%,rgba(11,31,58,0.16),transparent_74%)]" />
      <div className="absolute -left-[16%] top-[24%] h-[310px] w-[82%] rotate-[-9deg] rounded-[50%] border border-[#0b1f3a]/[0.14] bg-[#e4edf8]/85 blur-[1px]" />
      <div className="absolute -right-[17%] top-[32%] h-[270px] w-[86%] rotate-[8deg] rounded-[50%] border border-[#e60000]/[0.14] bg-[#ffeded]/90 blur-[1px]" />
      <div className="absolute -left-[10%] bottom-[-120px] h-[290px] w-[72%] rotate-[5deg] rounded-[50%] bg-[#0b1f3a]/[0.09]" />
      <div className="absolute -right-[8%] bottom-[-135px] h-[280px] w-[64%] rotate-[-5deg] rounded-[50%] bg-[#e60000]/[0.11]" />
      <div className="absolute inset-x-0 top-0 h-[510px] bg-[linear-gradient(rgba(11,31,58,0.04)_1px,transparent_1px),linear-gradient(90deg,rgba(11,31,58,0.04)_1px,transparent_1px)] bg-[size:46px_46px] [mask-image:linear-gradient(to_bottom,black,transparent)]" />
    </div>
  );
}
