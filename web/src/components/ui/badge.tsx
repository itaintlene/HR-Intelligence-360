import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    variant: {
      default: "border-transparent bg-primary text-primary-foreground",
      secondary: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-foreground",
      critical: "border-transparent bg-red-100 text-red-800",
      high: "border-transparent bg-orange-100 text-orange-800",
      medium: "border-transparent bg-amber-100 text-amber-800",
      low: "border-transparent bg-emerald-100 text-emerald-800",
      success: "border-transparent bg-emerald-100 text-emerald-800",
      warning: "border-transparent bg-amber-100 text-amber-800",
      danger: "border-transparent bg-red-100 text-red-800",
    },
  },
  defaultVariants: { variant: "default" },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}
export const Badge = ({ className, variant, ...p }: BadgeProps) => <span className={cn(badgeVariants({ variant }), className)} {...p} />;
