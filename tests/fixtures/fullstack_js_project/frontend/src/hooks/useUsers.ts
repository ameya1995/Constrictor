import useSWR from "swr";

export function useUsers() {
  const { data, error } = useSWR("/api/users");
  return { users: data, error };
}

export function useOrders() {
  const { data, error } = useSWR("/api/orders");
  return { orders: data, error };
}
