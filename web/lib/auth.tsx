"use client";

import React, { createContext, useCallback, useContext } from "react";
import { useAuth as useClerkAuth, useClerk } from "@clerk/nextjs";

interface AuthCtx {
  /** Get the current Clerk session JWT (refreshes automatically). Returns null if not signed in. */
  getToken: () => Promise<string | null>;
  /** True while Clerk is initialising. */
  isLoading: boolean;
  /** Sign out of Clerk and clear session. */
  logout: () => void;
}

const AuthContext = createContext<AuthCtx>({
  getToken: async () => null,
  isLoading: true,
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { isLoaded, getToken: clerkGetToken } = useClerkAuth();
  const { signOut } = useClerk();

  const getToken = useCallback(async (): Promise<string | null> => {
    try {
      return await clerkGetToken();
    } catch {
      return null;
    }
  }, [clerkGetToken]);

  const logout = useCallback(() => {
    void signOut();
  }, [signOut]);

  return (
    <AuthContext.Provider value={{ getToken, isLoading: !isLoaded, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
