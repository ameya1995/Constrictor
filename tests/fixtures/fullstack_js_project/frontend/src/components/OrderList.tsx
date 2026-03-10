import React from "react";
import axios from "axios";

interface Order {
  id: number;
  total: number;
}

async function fetchOrders(): Promise<Order[]> {
  const resp = await axios.get("/api/orders");
  return resp.data;
}

const OrderList: React.FC = () => {
  return <div>Orders</div>;
};

export default OrderList;
