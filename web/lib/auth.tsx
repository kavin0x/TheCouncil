"use client";

import React, { createContext, useCallback, useContext } from "react";

interface AuthCtx {
  getToken: () => Promise<string | null>;
  isLoading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthCtx>({
  getToken: async () => null,
  isLoading: false,
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const apiToken = process.env.NEXT_PUBLIC_API_TOKEN ?? null;

  const getToken = useCallback(async (): Promise<string | null> => {
    return apiToken;
  }, [apiToken]);

  return (
    <AuthContext.Provider value={{ getToken, isLoading: false, logout: () => {} }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
