"use client";

import { initializePaddle, type Paddle } from "@paddle/paddle-js";

let paddleInstancePromise: Promise<Paddle | undefined> | null = null;

/** Loads + initializes Paddle.js exactly once and reuses the same instance
 * across calls — Paddle.js should not be re-initialized on every render. */
function getPaddleInstance(environment: "sandbox" | "live"): Promise<Paddle | undefined> {
  const token = process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN;
  if (!token) {
    return Promise.resolve(undefined);
  }
  if (!paddleInstancePromise) {
    paddleInstancePromise = initializePaddle({
      environment: environment === "live" ? "production" : "sandbox",
      token,
    });
  }
  return paddleInstancePromise;
}

export async function openPaddleCheckout(options: {
  environment: "sandbox" | "live";
  priceId: string;
  customerId: string;
}): Promise<void> {
  const paddle = await getPaddleInstance(options.environment);
  if (!paddle) {
    throw new Error("Paddle.js is not configured (missing client token)");
  }
  paddle.Checkout.open({
    items: [{ priceId: options.priceId, quantity: 1 }],
    customer: { id: options.customerId },
  });
}
