import React from "react";
import UserList from "./UserList";
import OrderList from "./OrderList";

const App: React.FC = () => {
  return (
    <div>
      <UserList />
      <OrderList />
    </div>
  );
};

export default App;
