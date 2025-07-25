import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
import pytz

st.set_page_config(page_title="Lowe's Data Merge Tool", layout="wide")
st.title("Merge Lowes Data Files")
st.markdown("""
Upload **Orders**, **Shipments**, and **Invoices** files to generate a merged Excel report.  
Files must be in the original SPS downloaded format or copy and pasted into a separate Excel using the exact same format.""")

#helpers
def format_date(series):
    return pd.to_datetime(series, errors="coerce").dt.strftime("%m/%d/%Y")

def pick_notna(series):
    return series.dropna().iloc[0] if not series.dropna().empty else ""

#file uploads
uploaded_orders = st.file_uploader("Upload Orders File (.xlsx)", type="xlsx")
uploaded_shipments = st.file_uploader("Upload Shipments File (.xlsx)", type="xlsx")
uploaded_invoices = st.file_uploader("Upload Invoices File (.xlsx)", type="xlsx")

#progress bar
if uploaded_orders and uploaded_shipments and uploaded_invoices:
    progress = st.progress(0, text="Reading Files... (give it a second)")

    orders = pd.read_excel(uploaded_orders, dtype=str)
    shipments = pd.read_excel(uploaded_shipments, dtype=str)
    invoices = pd.read_excel(uploaded_invoices, dtype=str)

    shipments.columns = shipments.columns.str.strip()
    invoices.columns = invoices.columns.str.strip()

    #fill missing record types with invoice purpose
    if "Record Type" in invoices.columns and "Invoice purpose" in invoices.columns:
        invoices["Record Type"] = invoices["Record Type"].fillna(invoices["Invoice purpose"])

    progress.progress(20, text="Cleaning Order File...")

    #maps
    vbu_mapping = {
        118871: "Fostoria", 118872: "Jackson", 503177: "Longwood", 503255: "Greenville",
        502232: "Milazzo", 505071: "Claymont", 505496: "Gaylord", 505085: "Spring Valley Ice Melt",
        114037: "PCI Nitrogen", 501677: "Theremorock East Inc"}

    vendor_item_mapping = {
        "4983612": "B8110200", "4983613": "B8110300", "5113267": "B8110100", "5516714": "B8100731",
        "5516715": "B8100733", "5516716": "B8100732", "552704": "B1195010", "72931": "B1224080",
        "1053900": "", "148054": "B1298200", "147992": "B1288200", "72801": "B1202380",
        "94833": "B1260080", "961539": "B1258800", "120019": "B1200190", "92384": "I0002776",
        "71918": "B1246150", "71894": "B1246160", "101760": "B2063400", "92951": "B1224060",
        "91900": "B1202360", "97086": "B1260060", "1330491": "B4292000", "91299": "B1202390",
        "335457": "B2241150", "1240180": "B1242620", "97809": "B1201460", "167411": "B1237440",
        "335456": "B1195080", "197914": "B1195060", "552706": "B1195050", "552696": "B1195020",
        "552697": "B1195040", "45379": "B1200190"}

    #clean
    orders.columns = orders.columns.str.strip().str.replace("PO Line #", "PO Line#", regex=False)

    #handle Product/Item Description or Item columns
    if "Product/Item Description" in orders.columns:
        orders["Item Name"] = orders["Product/Item Description"]
    elif "Item" in orders.columns:
        orders["Item Name"] = orders["Item"]
    else:
        st.error("Missing both 'Product/Item Description' and 'Item' columns in orders file.")
        st.stop()

    required_order_cols = ["PO Line#", "Qty Ordered"]
    for col in required_order_cols:
        if col not in orders.columns:
            st.error(f"Missing required column in orders file: '{col}'")
            st.write("Columns found:", list(orders.columns))
            st.stop()

    orders["PO Line#"] = pd.to_numeric(orders["PO Line#"], errors="coerce")
    orders["Qty Ordered"] = pd.to_numeric(orders["Qty Ordered"], errors="coerce")

    headers = orders[(orders["PO Line#"].isna()) & (orders["Qty Ordered"].isna())].copy()

    details = orders[(orders["PO Line#"].notna()) | (orders["Qty Ordered"].notna())].copy()

    meta_cols = [
        "PO Number", "PO Date", "Vendor #",
        "Ship To Name", "Ship To City", "Ship To State", "Requested Delivery Date"]

    headers_meta = headers[meta_cols].drop_duplicates(subset=["PO Number"])

    orders = details.merge(headers_meta, on="PO Number", how="left", suffixes=("", "_hdr"))

    for col in meta_cols[1:]:
        orders[col] = orders[col].combine_first(orders[f"{col}_hdr"])
        orders.drop(columns=[f"{col}_hdr"], inplace=True)

    #fields
    orders["Item#"] = orders["Buyers Catalog or Stock Keeping #"]
    orders["Vendor Item#"] = orders["Item#"].map(vendor_item_mapping)
    orders["VBU#"] = pd.to_numeric(orders["Vendor #"], errors="coerce")
    orders["VBU Name"] = orders["VBU#"].map(vbu_mapping)
    orders["Unit Price"] = pd.to_numeric(orders["Unit Price"], errors="coerce").round(2)
    orders["Merch Total"] = (orders["Qty Ordered"] * orders["Unit Price"]).round(2)

    orders["Requested Delivery Date"] = format_date(orders["Requested Delivery Date"])
    orders["PO Date"] = format_date(orders["PO Date"])
    orders["PO Date Sortable"] = pd.to_datetime(orders["PO Date"], errors="coerce")
    orders["PO Num Sort"] = pd.to_numeric(orders["PO Number"], errors="coerce")

    orders = orders.sort_values(by=["PO Date Sortable", "PO Num Sort"], ascending=[False, False])

    #shipments
    progress.progress(40, text="Merging Shipment File...")

    shipments = shipments.rename(columns={"PO #": "PO Number", "Buyer Item #": "Item#"})
    shipment_cols = ["PO Number", "Item#", "Location #", "ASN Date", "Ship Date", "BOL", "SCAC", "ASN #"]
    shipments = shipments[[col for col in shipment_cols if col in shipments.columns]].copy()

    if "ASN Date" in shipments:
        shipments["ASN Date"] = format_date(shipments["ASN Date"])
    if "Ship Date" in shipments:
        shipments["Ship Date"] = format_date(shipments["Ship Date"])

    orders = orders.merge(shipments, how="left", on=["PO Number", "Item#"])
    orders.rename(columns={
        "BOL": "BOL#",
        "ASN #": "ASN#"}, inplace=True)

    #invoices
    progress.progress(60, text="Merging Invoice File...")

    invoices = invoices.rename(columns={"Retailers PO #": "PO Number"})
    
    if "Merchandise Total" in invoices.columns:
        invoices["Merchandise Total"] = pd.to_numeric(
            invoices["Merchandise Total"], errors="coerce").round(2)
        
    if "Discounted Amounted_Discount Amount" in invoices.columns:
        invoices["Discounted Amounted_Discount Amount"] = pd.to_numeric(
            invoices["Discounted Amounted_Discount Amount"], errors="coerce").round(2)
        
    if "Invoice Date" in invoices.columns:
        invoices["Invoice Date"] = format_date(invoices["Invoice Date"])

    invoice_grouped = (
        invoices
        .groupby("PO Number")
        .agg({
            "Invoice Number": pick_notna,
            "Invoice Date": pick_notna,
            "Merchandise Total": pick_notna,
            "Discounted Amounted_Discount Amount": pick_notna}).reset_index())

    invoice_grouped = invoice_grouped.rename(columns={
        "Invoice Number": "Invoice#",
        "Invoice Date": "Invoice Date",
        "Merchandise Total": "Merch. Total",
        "Discounted Amounted_Discount Amount": "Invoice Disc."})

    orders = orders.merge(invoice_grouped, on="PO Number", how="left", validate="many_to_one")

    orders["Merch. Total"] = pd.to_numeric(orders["Merch. Total"], errors="coerce").fillna(0)
    orders["Invoice Disc."] = pd.to_numeric(orders["Invoice Disc."], errors="coerce").fillna(0)
    orders["Net Invoiced"] = (orders["Merch. Total"] - orders["Invoice Disc."]).round(2)

    #turn 0s to blanks
    orders.loc[orders["Merch. Total"] == 0, "Merch. Total"] = ""
    orders.loc[orders["Invoice Disc."] == 0, "Invoice Disc."] = ""
    orders.loc[orders["Net Invoiced"] == 0, "Net Invoiced"] = ""

    progress.progress(80, text="Adding finishing touches...")

    orders["Fulfillment Status"] = "Not Shipped"
    orders.loc[pd.notna(orders["Ship Date"]), "Fulfillment Status"] = "Shipped Not Invoiced"
    orders.loc[pd.notna(orders["Invoice#"]), "Fulfillment Status"] = "Invoiced"

    orders["Late Ship"] = pd.to_datetime(orders["Ship Date"], errors="coerce") > pd.to_datetime(orders["Requested Delivery Date"], errors="coerce")
    orders["Late Ship"] = orders["Late Ship"].map({True: "Yes", False: "No"}).fillna("")

    final_cols = [
        "PO Number", "PO Date", "VBU#", "VBU Name", "Item#", "Vendor Item#", "Item Name",
        "Qty Ordered", "Unit Price", "Merch Total", "PO Line#", "Ship To Name", "Ship To City", "Ship To State",
        "Requested Delivery Date", "Fulfillment Status", "Late Ship", "ASN Date", "Ship Date", "ASN#",
        "BOL#", "SCAC", "Invoice#", "Invoice Date", "Merch. Total", "Invoice Disc.", "Net Invoiced"]

    for col in final_cols:
        if col not in orders.columns:
            orders[col] = ""

    orders = orders.reindex(columns=final_cols).fillna("")

    tz = pytz.timezone("America/New_York")
    timestamp = datetime.now(tz).strftime("%Y-%m-%d_%H%M")
    filename = f"Lowes_Merged_{timestamp}.xlsx"

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        orders.to_excel(writer, index=False, sheet_name="Orders")
        workbook = writer.book
        worksheet = writer.sheets["Orders"]
        for idx, col in enumerate(orders.columns):
            worksheet.set_column(idx, idx, 20)
            header_format = workbook.add_format({"align": "left", "bold": True})
            worksheet.write(0, idx, col, header_format)

    file_size_kb = len(output.getvalue()) / 1024
    progress.progress(100, text="Complete")
    st.success(f"Your file is saved as **{filename}**")
    st.caption(f"Approx. file size: {file_size_kb:.1f} KB")
    st.info(f"Total merged rows: {len(orders):,}")
    st.download_button(
        "Download Merged Excel File",
        data=output.getvalue(),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
