import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge, Button, Card, CardContent, Progress, Skeleton } from "@/components/ui";

describe("Button", () => {
  it("renders children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: /click me/i })).toBeInTheDocument();
  });
  it("is disabled when disabled prop is set", () => {
    render(<Button disabled>Disabled</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
  it("applies outline variant classes", () => {
    render(<Button variant="outline">Outline</Button>);
    expect(screen.getByRole("button")).toHaveClass("border");
  });
});

describe("Badge", () => {
  it("renders text", () => {
    render(<Badge>Pro</Badge>);
    expect(screen.getByText("Pro")).toBeInTheDocument();
  });
  it("applies success variant", () => {
    render(<Badge variant="success">Active</Badge>);
    expect(screen.getByText("Active")).toHaveClass("text-emerald-400");
  });
});

describe("Card", () => {
  it("renders content", () => {
    render(
      <Card>
        <CardContent>Hello card</CardContent>
      </Card>
    );
    expect(screen.getByText("Hello card")).toBeInTheDocument();
  });
});

describe("Progress", () => {
  it("renders without crashing", () => {
    const { container } = render(<Progress value={50} />);
    expect(container.firstChild).toBeInTheDocument();
  });
});

describe("Skeleton", () => {
  it("renders with animate-pulse class", () => {
    const { container } = render(<Skeleton className="h-4 w-32" />);
    expect(container.firstChild).toHaveClass("animate-pulse");
  });
});
