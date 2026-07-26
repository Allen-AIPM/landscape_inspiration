import { useEffect, useMemo, useRef } from "react";
import { gsap } from "gsap";

const SplitText = ({
  text = "",
  className = "",
  delay = 35,
  duration = 0.85,
  ease = "power3.out",
  splitType = "chars",
  from = { opacity: 0, y: 34 },
  to = { opacity: 1, y: 0 },
  threshold = 0.1,
  textAlign = "left",
  tag = "p",
  onLetterAnimationComplete,
}) => {
  const ref = useRef(null);
  const completedRef = useRef(false);
  const Tag = tag || "p";

  const parts = useMemo(() => {
    if (splitType.includes("words")) {
      return text.split(/(\s+)/).map((part, index) => ({ value: part, key: `${part}-${index}`, space: /^\s+$/.test(part) }));
    }
    return Array.from(text).map((part, index) => ({ value: part, key: `${part}-${index}`, space: part === " " }));
  }, [text, splitType]);

  useEffect(() => {
    if (!ref.current || completedRef.current) return undefined;
    const element = ref.current;
    const targets = element.querySelectorAll(".split-char");

    const animate = () => {
      gsap.fromTo(
        targets,
        { ...from },
        {
          ...to,
          duration,
          ease,
          stagger: delay / 1000,
          onComplete: () => {
            completedRef.current = true;
            onLetterAnimationComplete?.();
          },
        },
      );
    };

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            animate();
            observer.disconnect();
          }
        });
      },
      { threshold },
    );

    gsap.set(targets, { ...from });
    observer.observe(element);

    return () => observer.disconnect();
  }, [delay, duration, ease, from, onLetterAnimationComplete, threshold, to]);

  return (
    <Tag ref={ref} className={`split-parent ${className}`} style={{ textAlign }}>
      {parts.map((part) =>
        part.space ? (
          <span className="split-space" key={part.key}>
            {part.value}
          </span>
        ) : (
          <span className="split-char" key={part.key}>
            {part.value}
          </span>
        ),
      )}
    </Tag>
  );
};

export default SplitText;
