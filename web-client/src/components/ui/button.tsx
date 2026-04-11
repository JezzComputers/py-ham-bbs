import * as React from "react";

const Button = React.forwardRef<HTMLButtonElement, React.ComponentProps<"button">>(({ className, type = "button", style, ...props }, ref) => {
	const computedStyle = { ...(style as React.CSSProperties) };
	const isDisabled = Boolean((props as React.ComponentProps<typeof Button> & { disabled?: boolean }).disabled);
	computedStyle.cursor = isDisabled ? "not-allowed" : "pointer";

	return (
		<button
			type={type}
			className={[
				"inline-flex h-10 items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium",
				"focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
				"disabled:pointer-events-none disabled:opacity-50",
				className,
			]
				.filter(Boolean)
				.join(" ")}
			ref={ref}
			style={computedStyle}
			{...props}
		/>
	);
});

Button.displayName = "Button";

export { Button };
