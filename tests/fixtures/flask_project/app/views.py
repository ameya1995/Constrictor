from flask import Blueprint, jsonify, request

bp = Blueprint("products", __name__)


@bp.route("/products", methods=["GET"])
def list_products():
    return jsonify([])


@bp.route("/products/<int:product_id>", methods=["GET"])
def get_product(product_id):
    return jsonify({"id": product_id})


@bp.route("/products", methods=["POST"])
def create_product():
    data = request.json
    return jsonify(data), 201


@bp.route("/products/<int:product_id>", methods=["PUT", "DELETE"])
def update_or_delete_product(product_id):
    if request.method == "DELETE":
        return "", 204
    return jsonify({"id": product_id})
