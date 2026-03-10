import React, { useEffect, useState } from "react";

interface User {
  id: number;
  name: string;
}

const UserList: React.FC = () => {
  const [users, setUsers] = useState<User[]>([]);

  useEffect(() => {
    fetchUsers();
  }, []);

  async function fetchUsers() {
    const response = await fetch("/api/users");
    const data = await response.json();
    setUsers(data);
  }

  return (
    <ul>
      {users.map((u) => (
        <li key={u.id}>{u.name}</li>
      ))}
    </ul>
  );
};

export default UserList;
