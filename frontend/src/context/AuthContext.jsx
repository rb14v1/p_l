// src/context/AuthContext.jsx
import React, { createContext, useState, useContext, useEffect } from "react";
import api from "../api/axios";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem("accessToken"));
  const [user, setUser] = useState(null);
  const [loadingUser, setLoadingUser] = useState(false);

  const fetchCurrentUser = async () => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      setUser(null);
      setIsLoggedIn(false);
      return;
    }

    setLoadingUser(true);
    try {
      const res = await api.get("/auth/user/"); 
      setUser(res.data);
      setIsLoggedIn(true);
    } catch (err) {
      console.error("Failed to fetch current user:", err);
      setUser(null);
      setIsLoggedIn(false);
      localStorage.removeItem("accessToken");
      localStorage.removeItem("refreshToken");
    } finally {
      setLoadingUser(false);
    }
  };
  useEffect(() => {
    if (localStorage.getItem("accessToken")) {
      fetchCurrentUser();
    }
  }, []);
  const login = async (tokens) => {
    try {
      localStorage.setItem("accessToken", tokens.access);
      localStorage.setItem("refreshToken", tokens.refresh);
      setIsLoggedIn(true);
      await fetchCurrentUser();
    } catch (err) {
      console.error("Login/Fetch user failed:", err);
      logout();
    }
  };

  const logout = () => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    setIsLoggedIn(false);
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider
      value={{
        isLoggedIn,
        user,
        loadingUser,
        isAdmin: !!(user && user.is_staff),
        login,
        logout,
        fetchCurrentUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  return useContext(AuthContext);
};
