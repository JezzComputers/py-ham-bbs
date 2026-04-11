import * as React from "react";

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(({ className, type, ...props }, ref) => {
	return (
		<input
			type={type}
			className={[
				"flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
				"placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2",
				"disabled:cursor-not-allowed disabled:opacity-50",
				className,
			]
				.filter(Boolean)
				.join(" ")}
			ref={ref}
			{...props}
		/>
	);
});

Input.displayName = "Input";

export { Input };
